//! Windows SQLite cache; each worker owns one connection and every statement.
use super::{windows::Library,packet};
use std::{ffi::{c_void,c_char,CString},path::Path,ptr};
use std::os::windows::ffi::OsStrExt;
type Handle=*mut c_void;
type Destructor=Option<unsafe extern "C" fn(*mut c_void)>;
struct Api {
    open:unsafe extern "C" fn(*const c_void,*mut Handle)->i32,
    close:unsafe extern "C" fn(Handle)->i32,
    prepare:unsafe extern "C" fn(Handle,*const c_char,i32,*mut Handle,*mut *const c_char)->i32,
    finalize:unsafe extern "C" fn(Handle)->i32,
    step:unsafe extern "C" fn(Handle)->i32,
    bind_text:unsafe extern "C" fn(Handle,i32,*const c_char,i32,Destructor)->i32,
    bind_blob:unsafe extern "C" fn(Handle,i32,*const c_void,i32,Destructor)->i32,
    column_blob:unsafe extern "C" fn(Handle,i32)->*const c_void,
    column_bytes:unsafe extern "C" fn(Handle,i32)->i32,
    column_int:unsafe extern "C" fn(Handle,i32)->i64,
    timeout:unsafe extern "C" fn(Handle,i32)->i32,
    _library:Library,
}
pub struct Cache {handle:Handle,api:Api,budget:usize}
struct Statement<'a>{cache:&'a Cache,handle:Handle}
impl Drop for Statement<'_>{fn drop(&mut self){unsafe{(self.cache.api.finalize)(self.handle);}}}
impl Drop for Cache{fn drop(&mut self){unsafe{(self.api.close)(self.handle);}}}
fn check(code:i32)->Result<(),String>{if code==0{Ok(())}else{Err(format!("SQLite operation failed ({code})"))}}
impl Cache {
    pub fn open(path:&Path,limit:usize)->Result<Self,String>{
        if limit==0{return Err("cache disabled".into());}
        if let Some(parent)=path.parent(){std::fs::create_dir_all(parent).map_err(|e|e.to_string())?;}
        let library=Library::load(Path::new("winsqlite3.dll"),true)?;
        let api=unsafe{Api{open:library.symbol(b"sqlite3_open16\0")?,close:library.symbol(b"sqlite3_close\0")?,
            prepare:library.symbol(b"sqlite3_prepare_v2\0")?,finalize:library.symbol(b"sqlite3_finalize\0")?,step:library.symbol(b"sqlite3_step\0")?,
            bind_text:library.symbol(b"sqlite3_bind_text\0")?,bind_blob:library.symbol(b"sqlite3_bind_blob\0")?,
            column_blob:library.symbol(b"sqlite3_column_blob\0")?,column_bytes:library.symbol(b"sqlite3_column_bytes\0")?,column_int:library.symbol(b"sqlite3_column_int64\0")?,
            timeout:library.symbol(b"sqlite3_busy_timeout\0")?,_library:library}};
        let mut wide:Vec<u16>=path.as_os_str().encode_wide().collect();if wide.contains(&0){return Err("invalid cache path".into());}wide.push(0);
        let mut handle=ptr::null_mut();let code=unsafe{(api.open)(wide.as_ptr().cast(),&mut handle)};
        if code!=0{if !handle.is_null(){unsafe{(api.close)(handle);}}return Err("cache open failed".into());}
        let cache=Self{handle,api,budget:limit*9/10};unsafe{(cache.api.timeout)(handle,100);}
        cache.exec("PRAGMA auto_vacuum=FULL")?;cache.exec(&format!("PRAGMA max_page_count={}",(limit/4096).max(4)))?;
        cache.exec("CREATE TABLE IF NOT EXISTS scenes (key TEXT PRIMARY KEY, data BLOB, used REAL)")?;Ok(cache)
    }
    fn prepare(&self,sql:&str)->Result<Statement<'_>,String>{
        let sql=CString::new(sql).map_err(|_|"invalid SQL")?;let mut handle=ptr::null_mut();
        let code=unsafe{(self.api.prepare)(self.handle,sql.as_ptr(),-1,&mut handle,ptr::null_mut())};
        if code!=0{if !handle.is_null(){unsafe{(self.api.finalize)(handle);}}return Err("cache statement failed".into());}
        Ok(Statement{cache:self,handle})
    }
    fn exec(&self,sql:&str)->Result<(),String>{
        let s=self.prepare(sql)?;loop{let code=unsafe{(self.api.step)(s.handle)};if code==101{return Ok(());}if code!=100{return Err(format!("cache write failed ({code})"));}}
    }
    fn scalar(&self,sql:&str)->Result<i64,String>{
        let s=self.prepare(sql)?;if unsafe{(self.api.step)(s.handle)}!=100{return Err("cache query failed".into());}Ok(unsafe{(self.api.column_int)(s.handle,0)})
    }
    fn key_exec(&self,sql:&str,key:&str)->Result<(),String>{
        let key=CString::new(key).map_err(|_|"invalid cache key")?;let s=self.prepare(sql)?;
        unsafe{check((self.api.bind_text)(s.handle,1,key.as_ptr(),-1,None))?;if (self.api.step)(s.handle)!=101{return Err("cache key write failed".into());}}Ok(())
    }
    pub fn load(&self,key:&str,scale:f64)->Result<Option<(packet::Scene,Vec<u8>)>,String>{
        if key.len()>256{return Ok(None);}
        let blob={
            let key=CString::new(key).map_err(|_|"invalid cache key")?;
            let s=self.prepare("SELECT data FROM scenes WHERE key=? AND length(data)<=268452456")?;
            unsafe{
                check((self.api.bind_text)(s.handle,1,key.as_ptr(),-1,None))?;
                if (self.api.step)(s.handle)!=100{return Ok(None);}
                let n=(self.api.column_bytes)(s.handle,0);let p=(self.api.column_blob)(s.handle,0);
                if n<=0||n as usize>packet::LIMIT+17000||p.is_null(){return Ok(None);}
                std::slice::from_raw_parts(p.cast::<u8>(),n as usize).to_vec()
            }
        };
        let scene=match packet::decode(&blob){Ok(scene) if scene.scale==scale=>scene,_=>return Ok(None)};
        self.key_exec("UPDATE scenes SET used=julianday('now') WHERE key=?",key)?;
        Ok(Some((scene,blob)))
    }
    pub fn save(&self,key:&str,data:&[u8])->Result<(),String>{
        if key.len()>256||data.len()>self.budget||data.len()>packet::LIMIT+17000{return Ok(());}
        self.exec("BEGIN IMMEDIATE")?;
        let result=(||{
            self.key_exec("DELETE FROM scenes WHERE key=?",key)?;
            while self.scalar("SELECT coalesce(sum(length(data)),0) FROM scenes")? as usize+data.len()>self.budget{
                self.exec("DELETE FROM scenes WHERE key=(SELECT key FROM scenes ORDER BY used LIMIT 1)")?;
            }
            let key=CString::new(key).map_err(|_|"invalid cache key")?;
            let s=self.prepare("INSERT INTO scenes VALUES(?,?,julianday('now'))")?;
            unsafe{
                check((self.api.bind_text)(s.handle,1,key.as_ptr(),-1,None))?;
                check((self.api.bind_blob)(s.handle,2,data.as_ptr().cast(),data.len() as i32,None))?;
                if (self.api.step)(s.handle)!=101{return Err("cache insert failed".into());}
            }drop(s);self.exec("COMMIT")
        })();
        if result.is_err(){let _=self.exec("ROLLBACK");}result
    }
}
