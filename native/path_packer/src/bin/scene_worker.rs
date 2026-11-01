//! Standalone reader worker. No interpreter, Qt, or Python ABI dependency.
#[cfg(all(feature="python",feature="worker"))]
compile_error!("Build worker with --no-default-features --features worker");
#[cfg(windows)] #[path="worker/windows.rs"] mod windows;
#[cfg(windows)] #[path="worker/packet.rs"] mod packet;
#[cfg(windows)] #[path="worker/cache.rs"] mod cache;
#[cfg(windows)]
use std::{path::PathBuf,time::Instant,io::Write};

#[cfg(windows)]
struct Args{input:PathBuf,output:PathBuf,bridge:PathBuf,sdk:PathBuf,version:String,page:i32,scale:f64,timeout:f64,
    viewport:Option<[f64;4]>,cache:Option<PathBuf>,key:Option<String>,budget:usize,workers:usize}
#[cfg(windows)]
impl Args{
    fn parse()->Result<Self,String>{
        let words:Vec<String>=std::env::args().skip(1).collect();
        if words.iter().any(|s|s=="--help"){return Err("Leaflet GPU scene worker: INPUT RESULT --bridge DLL --mupdf DLL --expected-mupdf VERSION [--page N --scale S --timeout T --viewport x0 y0 x1 y1 --cache-db DB --cache-limit BYTES --disk-cache-key KEY]".into());}
        let mut a=Self{input:PathBuf::new(),output:PathBuf::new(),bridge:PathBuf::new(),sdk:PathBuf::new(),version:String::new(),
            page:0,scale:1.,timeout:10.,viewport:None,cache:None,key:None,budget:0,workers:2};
        let mut i=0;let mut positional=0;
        while i<words.len(){let name=&words[i];i+=1;
            if !name.starts_with("--"){match positional{0=>a.input=PathBuf::from(name),1=>a.output=PathBuf::from(name),_=>return Err("too many worker paths".into())}positional+=1;continue;}
            if name=="--aggressive-band-merge"{continue;}
            let value=words.get(i).ok_or("missing worker option")?;i+=1;
            match name.as_str(){
                "--bridge"=>a.bridge=PathBuf::from(value),"--mupdf"=>a.sdk=PathBuf::from(value),"--expected-mupdf"=>a.version=value.clone(),
                "--page"=>a.page=value.parse().map_err(|_|"invalid page")?,"--scale"=>a.scale=value.parse().map_err(|_|"invalid scale")?,
                "--timeout"=>a.timeout=value.parse().map_err(|_|"invalid timeout")?,"--cache-db"=>a.cache=Some(PathBuf::from(value)),
                "--cache-limit"=>a.budget=value.parse().map_err(|_|"invalid cache budget")?,"--disk-cache-key"=>a.key=Some(value.clone()),
                "--transfer-workers"=>a.workers=value.parse().map_err(|_|"invalid transfer workers")?,"--base-scene"=>{},
                "--viewport"=>{let values=[value,words.get(i).ok_or("incomplete viewport")?,words.get(i+1).ok_or("incomplete viewport")?,words.get(i+2).ok_or("incomplete viewport")?];
                    let mut r=[0.;4];for (to,from) in r.iter_mut().zip(values){*to=from.parse::<f64>().map_err(|_|"invalid viewport")?;}i+=3;a.viewport=Some(r);},
                _=>return Err("unknown worker option".into())
            }
        }
        if positional!=2||a.bridge.as_os_str().is_empty()||a.sdk.as_os_str().is_empty()||a.version.is_empty()||a.page<0||!a.scale.is_finite()
            ||a.scale<1.||a.scale>64.||!a.timeout.is_finite()||a.timeout<0.||a.timeout>3600.||a.workers>4||a.budget>16*1024*1024*1024{
            return Err("invalid worker request".into());}
        if let Some(r)=a.viewport{if r.iter().any(|v|!v.is_finite())||r[2]<=r[0]||r[3]<=r[1]{return Err("invalid worker viewport".into());}}
        Ok(a)
    }
}
#[cfg(windows)]
fn compile(a:&Args,start:Instant)->Result<(Vec<u8>,Option<[f64;4]>),String>{
    let cache=if a.viewport.is_none()&&a.key.is_some(){a.cache.as_ref().and_then(|p|cache::Cache::open(p,a.budget).ok())}else{None};
    if let (Some(cache),Some(key))=(&cache,&a.key){if let Ok(Some((scene,encoded)))=cache.load(key,a.scale){
        return if a.workers==0{packet::encode(&scene,0).map(|b|(b,None))}else{Ok((encoded,None))};
    }}
    if start.elapsed().as_secs_f64()>=a.timeout{return Err("GPU scene time budget exceeded".into());}
    let native=windows::Native::load(&a.bridge,&a.sdk,&a.version)?;
    let mut viewport=a.viewport;
    let compiled={
        let mut job=native.open(&a.input,a.page,(a.timeout-start.elapsed().as_secs_f64()).max(0.))?;
        viewport=viewport.map(|r|[r[0].max(job.area[0]),r[1].max(job.area[1]),r[2].min(job.area[2]),r[3].min(job.area[3])]);
        if viewport.is_some_and(|r|r[2]<=r[0]||r[3]<=r[1]){return Err("invalid worker viewport".into());}
        let plan=_path_packer::scene_compiler::native_input::plan(job.metadata()?,job.area,a.scale,viewport)?;
        let data=job.materialize(&plan)?;
        _path_packer::scene_compiler::native_input::compile(data.bytes()?)?
    };
    let mut features=vec!["rust-compiler".into()];
    if compiled.images_bytes()>0{features.extend(["image".into(),"image-downsample".into(),"raster-shading".into()]);}
    if a.viewport.is_some(){features.push("viewport-images".into());}
    let scene=packet::Scene{scale:a.scale,commands:compiled.commands_len() as u32,features,packet:compiled.packet()?};drop(compiled);
    if start.elapsed().as_secs_f64()>=a.timeout{return Err("GPU scene time budget exceeded".into());}
    let encoded=packet::encode(&scene,a.workers)?;
    if let (Some(cache),Some(key))=(&cache,&a.key){
        if a.workers==0{if let Ok(compressed)=packet::encode(&scene,2){let _=cache.save(key,&compressed);}}
        else{let _=cache.save(key,&encoded);}
    }Ok((encoded,viewport))
}
#[cfg(windows)]
fn run(a:&Args)->Result<(),String>{
    let started=Instant::now();
    let (payload,error,viewport)=match compile(a,started){Ok((bytes,viewport))=>(bytes,false,viewport),Err(message)=>{
        let reason=if started.elapsed().as_secs_f64()>=a.timeout||message.contains("GPU scene time budget exceeded"){"GPU scene time budget exceeded".to_string()}
            else{format!("unsupported Rust GPU scene: {message}")};
        let bytes:Vec<_>=reason.chars().take(1024).collect::<String>().into_bytes();(bytes,true,a.viewport)
    }};
    let mut temporary=a.output.as_os_str().to_os_string();temporary.push(".tmp");let temporary=PathBuf::from(temporary);
    let result=(||{
        let mut file=std::fs::File::create(&temporary).map_err(|e|e.to_string())?;
        file.write_all(&packet::result_header(a.scale,viewport,error,payload.len())).map_err(|e|e.to_string())?;
        file.write_all(&payload).map_err(|e|e.to_string())?;file.flush().map_err(|e|e.to_string())?;drop(file);
        std::fs::rename(&temporary,&a.output).map_err(|e|e.to_string())
    })();if result.is_err(){let _=std::fs::remove_file(temporary);}result
}
fn main(){
    #[cfg(windows)]{match Args::parse().and_then(|a|run(&a)){Ok(())=>{},Err(e)=>{eprintln!("{e}");std::process::exit(1);}}}
    #[cfg(not(windows))]{eprintln!("Windows native worker required");std::process::exit(1);}
}
