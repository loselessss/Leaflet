//! Interoperable LFDC storage and LFSW private worker transport.
use super::windows::sha256;
pub const MAGIC:&[u8;8]=b"LFDC\x01\0\0\0";
pub const LIMIT:usize=256*1024*1024;
const CHUNK:usize=64*1024*1024;const BLOCK:usize=1024*1024;
pub struct Scene {pub scale:f64,pub commands:u32,pub features:Vec<String>,pub packet:Vec<u8>}
pub fn encode(scene:&Scene,workers:usize)->Result<Vec<u8>,String>{
    validate(scene)?;
    let mut out=MAGIC.to_vec();out.extend(scene.scale.to_le_bytes());out.extend(scene.commands.to_le_bytes());
    out.extend((scene.features.len() as u16).to_le_bytes());out.extend((scene.packet.len() as u64).to_le_bytes());
    out.extend((scene.packet.len().div_ceil(CHUNK) as u16).to_le_bytes());
    for feature in &scene.features{out.extend((feature.len() as u16).to_le_bytes());out.extend(feature.as_bytes());}
    let digest=sha256(&out,&scene.packet)?;out.extend(digest);
    for raw in scene.packet.chunks(CHUNK){
        let compressed=if workers>0&&raw.len()>=64*1024{compress(raw,workers)}else{None};
        let stored=compressed.as_deref().unwrap_or(raw);
        out.push(u8::from(compressed.is_some()));out.extend((raw.len() as u32).to_le_bytes());out.extend((stored.len() as u32).to_le_bytes());out.extend(stored);
    }Ok(out)
}
fn compress(raw:&[u8],workers:usize)->Option<Vec<u8>>{
    use std::sync::{Mutex,atomic::{AtomicUsize,Ordering}};
    let blocks:Vec<_>=raw.chunks(BLOCK).collect();let next=AtomicUsize::new(0);
    let results=Mutex::new(vec![Vec::new();blocks.len()]);
    let execute=||loop{let i=next.fetch_add(1,Ordering::Relaxed);if i>=blocks.len(){break;}
        let packed=lz4_flex::block::compress(blocks[i]);
        results.lock().unwrap()[i]=packed;};
    let n=workers.clamp(1,4).min(blocks.len()).min(std::thread::available_parallelism().map_or(1,|n|n.get()));
    std::thread::scope(|scope|{
        let mut threads=Vec::new();for _ in 1..n{if let Ok(t)=std::thread::Builder::new().spawn_scoped(scope,&execute){threads.push(t);}else{break;}}
        execute();for t in threads{t.join().expect("compression worker panicked");}
    });
    let results=results.into_inner().ok()?;let size=12+results.iter().map(|b|8+b.len()).sum::<usize>();
    if size>raw.len()*9/10{return None;}
    let mut out=Vec::with_capacity(size);out.extend(b"LFZ1");out.extend((raw.len() as u64).to_le_bytes());
    for (raw,packed) in blocks.iter().zip(results){out.extend((raw.len() as u32).to_le_bytes());out.extend((packed.len() as u32).to_le_bytes());out.extend(packed);}Some(out)
}
struct Reader<'a>{data:&'a [u8],at:usize}
impl<'a> Reader<'a>{
    fn take(&mut self,n:usize)->Result<&'a [u8],String>{if n>self.data.len()-self.at{return Err("truncated cached scene".into());}let p=&self.data[self.at..self.at+n];self.at+=n;Ok(p)}
    fn u16(&mut self)->Result<u16,String>{Ok(u16::from_le_bytes(self.take(2)?.try_into().unwrap()))}
    fn u32(&mut self)->Result<u32,String>{Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))}
    fn u64(&mut self)->Result<u64,String>{Ok(u64::from_le_bytes(self.take(8)?.try_into().unwrap()))}
}
fn validate(scene:&Scene)->Result<(),String>{
    if !scene.scale.is_finite()||!(1.0..=64.0).contains(&scene.scale)||scene.commands>1_048_576||scene.features.len()>64
        ||scene.features.iter().any(|s|s.is_empty()||s.len()>256)||scene.packet.len()>LIMIT||!scene.packet.starts_with(b"LFSC\x02\0\0\0"){
        return Err("invalid cached scene".into());}Ok(())
}
pub fn decode(data:&[u8])->Result<Scene,String>{
    if data.len()>LIMIT+17000{return Err("cached blob limit exceeded".into());}
    let mut r=Reader{data,at:0};if r.take(8)?!=MAGIC{return Err("unsupported cached scene".into());}
    let scale=f64::from_le_bytes(r.take(8)?.try_into().unwrap());let commands=r.u32()?;let count=r.u16()? as usize;let length=r.u64()?;
    let chunks=r.u16()? as usize;if length<8||length>LIMIT as u64||chunks!=(length as usize).div_ceil(CHUNK)||count>64{return Err("invalid cached scene budget".into());}
    let mut features=Vec::new();for _ in 0..count{let n=r.u16()? as usize;if n==0||n>256{return Err("invalid cached feature".into());}
        features.push(String::from_utf8(r.take(n)?.to_vec()).map_err(|_|"invalid cached UTF-8")?);}
    let prefix=r.at;let digest=r.take(32)?.to_vec();let mut packet=Vec::with_capacity(length as usize);
    for _ in 0..chunks{
        let codec=r.take(1)?[0];let raw=r.u32()? as usize;let stored=r.u32()? as usize;
        if raw!=CHUNK.min(length as usize-packet.len())||stored==0||stored>raw{return Err("invalid cached chunk size".into());}
        let bytes=r.take(stored)?;
        if codec==0{if stored!=raw{return Err("invalid raw chunk".into());}packet.extend(bytes);}
        else if codec==1{
            let mut b=Reader{data:bytes,at:0};if b.take(4)?!=b"LFZ1"||b.u64()?!=raw as u64{return Err("invalid LZ4 chunk".into());}
            let target=packet.len()+raw;while b.at<bytes.len(){let n=b.u32()? as usize;let stored=b.u32()? as usize;
                if n==0||n>BLOCK||n>target-packet.len(){return Err("invalid LZ4 block budget".into());}
                let packed=b.take(stored)?;let start=packet.len();packet.resize(start+n,0);
                let written=lz4_flex::block::decompress_into(packed,&mut packet[start..]).map_err(|_|"invalid LZ4 block")?;
                if written!=n{return Err("incomplete LZ4 block".into());}
            }if packet.len()!=target{return Err("incomplete LZ4 chunk".into());}
        }else{return Err("invalid cached codec".into());}
    }
    if r.at!=data.len()||packet.len()!=length as usize||sha256(&data[..prefix],&packet)?.as_slice()!=digest{return Err("corrupt cached scene".into());}
    let scene=Scene{scale,commands,features,packet};validate(&scene)?;Ok(scene)
}
pub fn result_header(scale:f64,viewport:Option<[f64;4]>,error:bool,length:usize)->Vec<u8>{
    let mut out=b"LFSW\x01\0\0\0".to_vec();out.extend(u32::from(error).to_le_bytes());out.extend(scale.to_le_bytes());out.extend(u32::from(viewport.is_some()).to_le_bytes());
    for x in viewport.unwrap_or([0.;4]){out.extend(x.to_le_bytes());}out.extend((length as u64).to_le_bytes());out
}
