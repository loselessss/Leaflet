//! The only unsafe boundary: owned DLLs, checked native buffers and Windows CNG.
use std::{ffi::{c_void,c_char,CStr,CString},path::Path,ptr};
use std::os::windows::ffi::OsStrExt;
type Handle=*mut c_void;
#[link(name="kernel32")]
unsafe extern "system" {
    fn LoadLibraryExW(path:*const u16,file:Handle,flags:u32)->Handle;
    fn GetProcAddress(module:Handle,name:*const c_char)->*mut c_void;
    fn FreeLibrary(module:Handle)->i32;
}
pub struct Library(Handle);
impl Library {
    pub fn load(path:&Path,system:bool)->Result<Self,String>{
        let mut wide:Vec<u16>=path.as_os_str().encode_wide().collect();
        if wide.contains(&0){return Err("invalid library path".into());}wide.push(0);
        let handle=unsafe{LoadLibraryExW(wide.as_ptr(),ptr::null_mut(),if system{0x800}else{0x1100})};
        if handle.is_null(){return Err(format!("native library unavailable: {}",std::io::Error::last_os_error()));}Ok(Self(handle))
    }
    pub unsafe fn symbol<T:Copy>(&self,name:&'static [u8])->Result<T,String>{
        let pointer=GetProcAddress(self.0,name.as_ptr().cast());
        if pointer.is_null()||std::mem::size_of::<T>()!=std::mem::size_of::<Handle>(){return Err("native entry point unavailable".into());}
        Ok(std::mem::transmute_copy(&pointer))
    }
}
impl Drop for Library{fn drop(&mut self){unsafe{FreeLibrary(self.0);}}}

type Open=unsafe extern "C" fn(*const c_char,i32,f64,*mut f64,*mut *const u8,*mut usize)->Handle;
type Materialize=unsafe extern "C" fn(Handle,*const u8,usize,*mut *const u8,*mut usize)->Handle;
type DropFn=unsafe extern "C" fn(Handle);
pub struct Native {
    open:Open,materialize:Materialize,drop_job:DropFn,drop_buffer:DropFn,
    error:unsafe extern "C" fn()->*const c_char,
    _bridge:Library,_sdk:Library,
}
impl Native {
    pub fn load(bridge:&Path,sdk:&Path,version:&str)->Result<Self,String>{
        let sdk=Library::load(sdk,false)?;let bridge=Library::load(bridge,false)?;
        unsafe{
            let abi:unsafe extern "C" fn()->u32=bridge.symbol(b"leaflet_scene_abi\0")?;
            let get_version:unsafe extern "C" fn()->*const c_char=bridge.symbol(b"leaflet_path_version\0")?;
            let actual_abi=abi();
            if actual_abi!=5{return Err(format!("native scene ABI mismatch (bridge={actual_abi}, worker=5)"));}
            let actual_version=CStr::from_ptr(get_version()).to_string_lossy();
            if actual_version!=version{return Err(format!("native MuPDF version mismatch (bridge={actual_version}, runtime={version})"));}
            Ok(Self{open:bridge.symbol(b"leaflet_scene_open\0")?,materialize:bridge.symbol(b"leaflet_scene_materialize\0")?,
                drop_job:bridge.symbol(b"leaflet_scene_drop\0")?,drop_buffer:bridge.symbol(b"leaflet_path_drop\0")?,
                error:bridge.symbol(b"leaflet_scene_error\0")?,_bridge:bridge,_sdk:sdk})
        }
    }
    fn message(&self)->String{unsafe{let p=(self.error)();if p.is_null(){"native PDF failure".into()}else{CStr::from_ptr(p).to_string_lossy().into_owned()}}}
    pub fn open<'a>(&'a self,path:&Path,page:i32,timeout:f64)->Result<Job<'a>,String>{
        let path=CString::new(path.to_str().ok_or("invalid PDF path")?).map_err(|_|"invalid PDF path")?;
        let mut area=[0.;4];let mut data=ptr::null();let mut length=0;
        let handle=unsafe{(self.open)(path.as_ptr(),page,timeout,area.as_mut_ptr(),&mut data,&mut length)};
        if handle.is_null(){return Err(self.message());}
        let job=Job{native:self,handle,data,length,area};job.metadata()?;Ok(job)
    }
}
pub struct Job<'a>{native:&'a Native,handle:Handle,data:*const u8,length:usize,pub area:[f64;4]}
impl Job<'_>{
    pub fn metadata(&self)->Result<&[u8],String>{checked_bytes(self.data,self.length)}
    pub fn materialize(&mut self,requests:&[u8])->Result<Buffer<'_>,String>{
        let mut data=ptr::null();let mut length=0;
        let handle=unsafe{(self.native.materialize)(self.handle,requests.as_ptr(),requests.len(),&mut data,&mut length)};
        if handle.is_null(){return Err(self.native.message());}
        let buffer=Buffer{native:self.native,handle,data,length};buffer.bytes()?;Ok(buffer)
    }
}
impl Drop for Job<'_>{fn drop(&mut self){unsafe{(self.native.drop_job)(self.handle);}}}
pub struct Buffer<'a>{native:&'a Native,handle:Handle,data:*const u8,length:usize}
impl Buffer<'_>{pub fn bytes(&self)->Result<&[u8],String>{checked_bytes(self.data,self.length)}}
impl Drop for Buffer<'_>{fn drop(&mut self){unsafe{(self.native.drop_buffer)(self.handle);}}}
fn checked_bytes<'a>(data:*const u8,length:usize)->Result<&'a [u8],String>{
    if length>512*1024*1024||(length>0&&data.is_null()){return Err("native buffer budget exceeded".into());}
    if length==0{Ok(&[])}else{Ok(unsafe{std::slice::from_raw_parts(data,length)})}
}

#[link(name="bcrypt")]
unsafe extern "system" {
    fn BCryptOpenAlgorithmProvider(out:*mut Handle,name:*const u16,provider:*const u16,flags:u32)->i32;
    fn BCryptGetProperty(handle:Handle,name:*const u16,data:*mut u8,size:u32,written:*mut u32,flags:u32)->i32;
    fn BCryptCreateHash(algorithm:Handle,out:*mut Handle,object:*mut u8,size:u32,secret:*const u8,secret_size:u32,flags:u32)->i32;
    fn BCryptHashData(hash:Handle,data:*const u8,size:u32,flags:u32)->i32;
    fn BCryptFinishHash(hash:Handle,data:*mut u8,size:u32,flags:u32)->i32;
    fn BCryptDestroyHash(hash:Handle)->i32;
    fn BCryptCloseAlgorithmProvider(algorithm:Handle,flags:u32)->i32;
}
struct Algorithm(Handle);impl Drop for Algorithm{fn drop(&mut self){unsafe{BCryptCloseAlgorithmProvider(self.0,0);}}}
struct Hash(Handle);impl Drop for Hash{fn drop(&mut self){unsafe{BCryptDestroyHash(self.0);}}}
fn wide(s:&str)->Vec<u16>{s.encode_utf16().chain(Some(0)).collect()}
fn success(code:i32)->Result<(),String>{if code<0{Err("native SHA-256 failure".into())}else{Ok(())}}
pub fn sha256(prefix:&[u8],data:&[u8])->Result<[u8;32],String>{
    unsafe{
        let mut algorithm=ptr::null_mut();success(BCryptOpenAlgorithmProvider(&mut algorithm,wide("SHA256").as_ptr(),ptr::null(),0))?;
        let algorithm=Algorithm(algorithm);let mut length=0u32;let mut written=0;
        success(BCryptGetProperty(algorithm.0,wide("ObjectLength").as_ptr(),(&mut length as *mut u32).cast(),4,&mut written,0))?;
        if length>1024*1024{return Err("invalid hash object size".into());}
        let mut object=vec![0u8;length as usize];let mut hash=ptr::null_mut();
        success(BCryptCreateHash(algorithm.0,&mut hash,object.as_mut_ptr(),length,ptr::null(),0,0))?;let hash=Hash(hash);
        for input in [prefix,data]{for block in input.chunks(64*1024*1024){success(BCryptHashData(hash.0,block.as_ptr(),block.len() as u32,0))?;}}
        let mut output=[0;32];success(BCryptFinishHash(hash.0,output.as_mut_ptr(),32,0))?;Ok(output)
    }
}
