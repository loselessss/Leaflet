//! Owned scene compiler. Production input is native_input; Python import is a comparison oracle.
#[cfg(feature="python")]
use pyo3::prelude::*;
#[cfg(feature="python")]
use pyo3::types::{PyBytes,PyTuple};
#[cfg(feature="python")]
use pyo3::exceptions::PyValueError;
use serde::Serialize;
use bincode::Options;
use std::collections::HashMap;
use std::hash::{Hash,Hasher};
pub mod native_input;

type Matrix=[f64;6];
type Rect=[f64;4];
const IDENTITY:Matrix=[1.,0.,0.,1.,0.,0.];
const LIMIT:usize=256*1024*1024;
const IMAGE_LIMIT:usize=128*1024*1024;
const COMMAND_LIMIT:usize=1_048_576;
const DEPTH_LIMIT:usize=4096;

#[derive(Serialize,Clone)]
enum Resource { Path(Vec<u8>), Image{pixels:Vec<u8>,width:u32,height:u32,stride:u32}, Mesh(Vec<u8>), Jpeg{bytes:Vec<u8>,width:u32,height:u32,target_width:u32,target_height:u32} }

#[derive(Serialize,Clone)]
struct Stroke {start:u32,dash:u32,end:u32,join:u32,miter:f64,phase:f64,dashes:Vec<f64>}

#[derive(Serialize,Clone)]
enum Operation {
    Path{resource:u32,fill:Option<u32>,stroke:Option<u32>,width:f64,style:Option<Stroke>,even_odd:bool,groupable:bool,shading:bool,instanced:bool},
    Clip{resource:u32,even_odd:bool},
    StrokeClip{resource:u32,width:f64,style:Option<Stroke>},
    Image{resource:u32,opacity:f64,interpolate:bool},
    Linear{resource:u32,start:[f64;2],end:[f64;2],stops:Vec<(f64,u32)>,even_odd:bool},
    Radial{resource:u32,center:[f64;2],origin:[f64;2],radius:[f64;2],stops:Vec<(f64,u32)>,even_odd:bool},
    Group{opacity:f64,blend:u32,isolated:bool,knockout:bool},
    GroupEnd,Mask{area:Rect,luminosity:bool,background:u32},MaskEnd{transfer:Vec<f64>},ClipEnd,
    GeometryGroup{sources:Vec<(u32,Matrix)>,fill:u32,even_odd:bool},
    BackdropImage{resource:u32,interpolate:bool},
    Mesh{resource:u32},
    CoverageBegin,
    CoverageEnd,
}

#[derive(Serialize,Clone)]
struct Command {op:Operation,matrix:Matrix,bounds:Option<Rect>,scope_end:Option<u32>,capture_end:Option<u32>,complex_depth:u32,native_opcode:u32,axis_clip:Option<Rect>}

#[derive(Serialize)]
struct Scene {resources:Vec<Resource>,commands:Vec<Command>,resource_bytes:usize,image_bytes:usize,
    #[serde(skip)] preparation:u32}

#[cfg(feature="python")]
type CompileError=pyo3::PyErr;
#[cfg(not(feature="python"))]
type CompileError=String;
pub type CompileResult<T>=Result<T,CompileError>;
#[cfg(feature="python")]
fn invalid(message:&str)->CompileError {PyValueError::new_err(message.to_string())}
#[cfg(not(feature="python"))]
fn invalid(message:&str)->CompileError {message.to_string()}
fn finite(values:&[f64])->CompileResult<()> {
    if values.iter().any(|x|!x.is_finite()) {return Err(invalid("non-finite compiler input"));} Ok(())
}
fn validate_path(data:&[u8])->CompileResult<()> {
    let mut offset=0;let mut count=0;
    while offset<data.len() {
        let coordinates=match data[offset]{1|2=>2,3=>6,4=>0,_=>return Err(invalid("invalid compiler path tag"))};
        offset+=1;
        if data.len()-offset<coordinates*8{return Err(invalid("truncated compiler path"));}
        for value in data[offset..offset+coordinates*8].chunks_exact(8){
            if !f64::from_le_bytes(value.try_into().unwrap()).is_finite(){return Err(invalid("non-finite compiler path"));}
        }
        offset+=coordinates*8;count+=1;
        if count>COMMAND_LIMIT{return Err(invalid("compiler path segment limit exceeded"));}
    }
    Ok(())
}
#[cfg(feature="python")]
fn matrix(item:&Bound<'_,PyAny>)->CompileResult<Matrix> {
    let value=item.getattr("transform")?;
    let result=if value.is_none(){IDENTITY}else{value.extract()?};finite(&result)?;Ok(result)
}
#[cfg(feature="python")]
fn stroke(item:&Bound<'_,PyAny>)->CompileResult<Option<Stroke>> {
    let value=item.getattr("stroke_style")?;
    if value.is_none(){return Ok(None);}
    let (start,dash,end,join,miter,phase,dashes):(u32,u32,u32,u32,f64,f64,Vec<f64>)=value.extract()?;
    finite(&[miter,phase])?;finite(&dashes)?;
    if start>3||dash>3||end>3||join>3||miter<0.||dashes.len()>4096||dashes.iter().any(|x|*x<0.) {
        return Err(invalid("invalid compiler stroke style"));
    }
    Ok(Some(Stroke{start,dash,end,join,miter,phase,dashes}))
}
#[cfg(feature="python")]
fn stops(item:&Bound<'_,PyAny>)->CompileResult<Vec<(f64,u32)>> {
    let values:Vec<(f64,u32)>=item.getattr("stops")?.extract()?;
    if values.is_empty()||values.len()>65536 {return Err(invalid("invalid gradient stop count"));}
    for (position,_) in &values {finite(&[*position])?;if !(0.0..=1.0).contains(position){return Err(invalid("invalid gradient position"));}}
    if values.windows(2).any(|pair|pair[0].0>pair[1].0){return Err(invalid("unordered gradient stops"));}
    Ok(values)
}
#[cfg(feature="python")]
fn opacity(item:&Bound<'_,PyAny>)->CompileResult<f64> {
    let result:f64=item.getattr("opacity")?.extract()?;
    if !result.is_finite()||!(0.0..=1.0).contains(&result){return Err(invalid("invalid opacity"));}Ok(result)
}

fn axis_rectangle(data:&[u8],matrix:&Matrix)->Option<Rect> {
    if matrix[1].abs()>1e-8||matrix[2].abs()>1e-8{return None;}
    let mut points=Vec::new();let mut offset=0;
    while offset<data.len() {
        let kind=data[offset];offset+=1;
        if kind==4{continue;}
        if kind!=1&&kind!=2{return None;}
        if data.len()-offset<16{return None;}
        let x=f64::from_le_bytes(data[offset..offset+8].try_into().ok()?);
        let y=f64::from_le_bytes(data[offset+8..offset+16].try_into().ok()?);offset+=16;
        points.push((x,y));if points.len()>5{return None;}
    }
    if points.len()==5&&points.first()==points.last(){points.pop();}
    if points.len()!=4{return None;}
    let mut xs=Vec::new();let mut ys=Vec::new();
    for i in 0..4 {
        if points[..i].contains(&points[i]){return None;}
        let (x,y)=points[i];let next=points[(i+1)%4];if x!=next.0&&y!=next.1{return None;}
        if !xs.contains(&x){xs.push(x);}if !ys.contains(&y){ys.push(y);}
    }
    if xs.len()!=2||ys.len()!=2{return None;}
    Some([xs[0].min(xs[1]),ys[0].min(ys[1]),xs[0].max(xs[1]),ys[0].max(ys[1])])
}

impl Scene {
    fn new()->Self {Self{resources:Vec::new(),commands:Vec::new(),resource_bytes:0,image_bytes:0,preparation:0}}
    fn intern(&mut self,resource:Resource,index:&mut HashMap<u64,Vec<u32>>)->CompileResult<u32> {
        let (kind,bytes,dimensions)=match &resource {
            Resource::Path(data)=>(1u8,data.as_slice(),[0,0,0,0]),
            Resource::Image{pixels,width,height,stride}=>(2,pixels.as_slice(),[*width,*height,*stride,0]),
            Resource::Mesh(data)=>(3,data.as_slice(),[0,0,0,0]),
            Resource::Jpeg{bytes,width,height,target_width,target_height}=>(4,bytes.as_slice(),[*width,*height,*target_width,*target_height]),
        };
        let mut hash=std::collections::hash_map::DefaultHasher::new();kind.hash(&mut hash);dimensions.hash(&mut hash);bytes.hash(&mut hash);
        let hash=hash.finish();
        if let Some(ids)=index.get(&hash) {
            for id in ids {
                let equal=match (&self.resources[*id as usize],&resource) {
                    (Resource::Path(a),Resource::Path(b))=>a==b,
                    (Resource::Mesh(a),Resource::Mesh(b))=>a==b,
                    (Resource::Jpeg{bytes:a,width:aw,height:ah,target_width:atw,target_height:ath},Resource::Jpeg{bytes:b,width:bw,height:bh,target_width:btw,target_height:bth})=>a==b&&aw==bw&&ah==bh&&atw==btw&&ath==bth,
                    (Resource::Image{pixels:a,width:aw,height:ah,stride:ast},Resource::Image{pixels:b,width:bw,height:bh,stride:bst})=>a==b&&aw==bw&&ah==bh&&ast==bst,
                    _=>false,
                };
                if equal{return Ok(*id);}
            }
        }
        self.resource_bytes=self.resource_bytes.checked_add(bytes.len()).ok_or_else(||invalid("resource overflow"))?;
        if self.resource_bytes>LIMIT{return Err(invalid("compiler resource budget exceeded"));}
        if kind==2||kind==4 {
            // Encoded storage is small, but decoded GPU memory remains bounded.
            let cost=if kind==4{dimensions[2] as usize*dimensions[3] as usize*4}else{bytes.len()};
            self.image_bytes+=cost;if self.image_bytes>IMAGE_LIMIT{return Err(invalid("compiler image budget exceeded"));}
        }
        let id=self.resources.len() as u32;self.resources.push(resource);index.entry(hash).or_default().push(id);Ok(id)
    }
    fn analyse(mut self)->CompileResult<Self> {
        // Source-over ink is affine in the initial backdrop. Its isolated
        // result is already the exact source recovered by two passes. Mask
        // construction uses its own target, independent of the outer backdrop.
        fn independent_source(input:&[Command])->bool{
            let mut masks=0usize;
            for command in input {
                match command.op {
                    Operation::Mask{..}=>{masks+=1;continue;},
                    Operation::MaskEnd{..}=>{masks=masks.saturating_sub(1);continue;},
                    _=>{},
                }
                if masks!=0{continue;}
                if matches!(command.op,Operation::Group{blend:1..,..}|
                    Operation::Group{knockout:true,..}|Operation::BackdropImage{..}|
                    Operation::CoverageBegin){return false;}
            }
            true
        }
        fn coverage_program(input:&[Command],depth:usize)->CompileResult<Vec<Command>>{
            let mut out=Vec::new();let mut i=0;
            while i<input.len(){
                if matches!(input[i].op,Operation::Group{blend:1..,isolated:false,knockout:false,..}){
                    if depth>=3{return Err(invalid("backdrop nesting budget"));}
                    let mut end=i+1;let mut nested=1;
                    while end<input.len(){match input[end].op{Operation::Group{..}=>nested+=1,Operation::GroupEnd=>{nested-=1;if nested==0{break;}},_=>{}}end+=1;}
                    if end==input.len(){return Err(invalid("unclosed backdrop group"));}
                    let body=coverage_program(&input[i+1..end],depth+1)?;
                    if independent_source(&body){
                        let mut open=input[i].clone();
                        if let Operation::Group{isolated,..}=&mut open.op{*isolated=true;}
                        out.push(open);out.extend(body);out.push(input[end].clone());i=end+1;continue;
                    }
                    let mut open=input[i].clone();open.op=Operation::CoverageBegin;out.push(open);
                    out.extend(body.iter().cloned());let mut close=input[end].clone();close.op=Operation::CoverageEnd;out.push(close);
                    out.push(input[i].clone());out.extend(body);out.push(input[end].clone());i=end+1;
                }else{out.push(input[i].clone());i+=1;}
                if out.len()>COMMAND_LIMIT{return Err(invalid("backdrop command budget"));}
            }Ok(out)
        }
        if self.commands.iter().any(|c|matches!(c.op,Operation::Group{blend:1..,isolated:false,knockout:false,..})){
            self.commands=coverage_program(&self.commands,0)?;
        }
        if self.commands.len()>COMMAND_LIMIT{return Err(invalid("compiler command count exceeded"));}
        // Match the existing reader's text geometry-group semantics, including
        // a single transformed glyph. Compilation policy stays in Rust.
        let mut compacted:Vec<Command>=Vec::new();
        for mut command in self.commands {
            if let Operation::Path{resource,fill:Some(fill),stroke:None,even_odd,instanced:true,..}=command.op {
                let mut joined=false;
                if let Some(previous)=compacted.last_mut() {
                    if let Operation::GeometryGroup{sources,fill:old,even_odd:old_even}=&mut previous.op {
                        if *old==fill&&*old_even==even_odd {
                            sources.push((resource,command.matrix));previous.bounds=None;joined=true;
                        }
                    }
                }
                if joined {continue;}
                command.op=Operation::GeometryGroup{sources:vec![(resource,command.matrix)],fill,even_odd};
                command.matrix=IDENTITY;
            }
            compacted.push(command);
        }
        self.commands=compacted;
        let composite=self.commands.iter().any(|command|matches!(command.op,Operation::CoverageBegin|Operation::Mask{..}|
            Operation::Group{blend:1.., ..}|Operation::Group{isolated:false,..}|Operation::Group{knockout:true,..}));
        let mut scopes:Vec<(u8,usize,bool)>=Vec::new();let mut complex=0u32;
        for i in 0..self.commands.len() {
            self.commands[i].complex_depth=complex;
            self.commands[i].native_opcode=match self.commands[i].op {
                Operation::Clip{..}|Operation::StrokeClip{..}=>2,
                Operation::Group{..}=>if composite{6}else{4},
                Operation::GroupEnd=>if composite{7}else{5},
                Operation::Mask{..}=>12,Operation::MaskEnd{..}=>13,Operation::ClipEnd=>3,_=>0,
            };
            if composite && matches!(self.commands[i].op,Operation::Mask{..}|Operation::Group{..}) {
                for (_,start,_) in &scopes {
                    if matches!(self.commands[*start].op,Operation::Clip{..}|Operation::StrokeClip{..}) {
                        self.commands[*start].native_opcode=8;
                    }
                }
            }
            match &self.commands[i].op {
                Operation::Clip{..}|Operation::StrokeClip{..}=>scopes.push((1,i,false)),
                Operation::Mask{..}=>{scopes.push((2,i,true));complex+=1;},
                Operation::CoverageBegin=>{scopes.push((4,i,true));complex+=1;},
                Operation::Group{blend,isolated,knockout,..}=>{
                    let barrier=*blend!=0||!*isolated||*knockout;
                    scopes.push((3,i,barrier));if barrier{complex+=1;}
                },
                Operation::MaskEnd{..}=>{
                    let last=scopes.last_mut().ok_or_else(||invalid("mask end without capture"))?;
                    if last.0!=2{return Err(invalid("mask end crosses scope"));}
                    self.commands[last.1].capture_end=Some(i as u32);last.0=1;
                    // The mask remains a composition barrier until ClipEnd.
                },
                Operation::ClipEnd|Operation::GroupEnd|Operation::CoverageEnd=>{
                    let expected=if matches!(self.commands[i].op,Operation::ClipEnd){1}else if matches!(self.commands[i].op,Operation::CoverageEnd){4}else{3};
                    let (kind,start,barrier)=scopes.pop().ok_or_else(||invalid("scope underflow"))?;
                    if kind!=expected{return Err(invalid("crossed compiler scope"));}
                    self.commands[start].scope_end=Some(i as u32);
                    if expected==1 {self.commands[i].native_opcode=if self.commands[start].native_opcode==8||matches!(self.commands[start].op,Operation::Mask{..}){9}else{3};}
                    if barrier {complex-=1;}
                },
                _=>{},
            }
            if scopes.len()>DEPTH_LIMIT{return Err(invalid("compiler scope depth exceeded"));}
        }
        if !scopes.is_empty(){return Err(invalid("unclosed compiler scope"));}
        for i in 0..self.commands.len() {
            if self.commands[i].native_opcode==2&&self.commands[i].axis_clip.is_some() {
                self.commands[i].native_opcode=19;
                if let Some(end)=self.commands[i].scope_end {self.commands[end as usize].native_opcode=20;}
            }
        }
        self.fold_gradient_opacity();
        Ok(self)
    }

    fn fold_gradient_opacity(&mut self) {
        // A Normal group containing one gradient only scales that source's
        // alpha. Keep the already planned clip captures: they may separate it
        // from a COPY/knockout target even after this group is removed.
        let n=self.commands.len();let mut remove=vec![false;n];
        let mut depth_delta=vec![0i32;n+1];let mut scopes:Vec<usize>=Vec::new();
        for i in 0..n {
            while scopes.last().is_some_and(|j|(self.commands[*j].scope_end.unwrap() as usize)<i){scopes.pop();}
            let group=match self.commands[i].op {
                Operation::Group{opacity,blend:0,isolated,knockout:false} if opacity<1.=>Some((opacity,isolated)),
                _=>None,
            };
            if let Some((opacity,isolated))=group {
                let end=self.commands[i].scope_end.unwrap() as usize;
                let masked=scopes.iter().any(|j|matches!(self.commands[*j].op,Operation::Mask{..}|Operation::CoverageBegin));
                let copy=scopes.iter().rev().find_map(|j|{
                    let c=&self.commands[*j];
                    if let Operation::Group{knockout,..}=c.op{Some(knockout)}
                    else if c.native_opcode==8{Some(false)}else{None}
                }).unwrap_or(false);
                if !masked&&!copy&&end-i<=64 {
                    let mut paint=None;let mut valid=true;
                    for j in i+1..end {match self.commands[j].op {
                        Operation::Linear{..}|Operation::Radial{..}=>{if paint.replace(j).is_some(){valid=false;break;}},
                        Operation::Clip{..}|Operation::StrokeClip{..}|Operation::ClipEnd=>{},
                        _=>{valid=false;break;},
                    }}
                    if valid {if let Some(j)=paint {
                        let stops=match &mut self.commands[j].op {
                            Operation::Linear{stops,..}|Operation::Radial{stops,..}=>stops,_=>unreachable!(),
                        };
                        for (_,color) in stops {
                            let alpha=(((*color>>24) as f64)*opacity).round_ties_even() as u32;
                            *color=(*color&0xffffff)|(alpha<<24);
                        }
                        remove[i]=true;remove[end]=true;
                        if !isolated {depth_delta[i+1]+=1;depth_delta[end]-=1;}
                    }}
                }
            }
            if self.commands[i].scope_end.is_some(){scopes.push(i);}
        }
        if !remove.iter().any(|v|*v){return;}
        let mut remap=vec![0u32;n];let mut next=0;
        for i in 0..n {remap[i]=next;if !remove[i]{next+=1;}}
        let mut depth=0i32;let mut index=0;
        self.commands.retain_mut(|c|{
            let i=index;index+=1;depth+=depth_delta[i];
            if remove[i]{return false;}
            c.scope_end=c.scope_end.map(|j|remap[j as usize]);
            c.capture_end=c.capture_end.map(|j|remap[j as usize]);
            c.complex_depth-=depth as u32;true
        });
    }
}

#[cfg(feature="python")]
fn import_scene(py:Python<'_>,input:&Bound<'_,PyAny>)->CompileResult<Scene> {
    if !input.getattr("supported")?.extract::<bool>()? {return Err(invalid("cannot compile unsupported scene"));}
    let mut scene=Scene::new();let mut index=HashMap::new();
    let items=input.getattr("drawables")?;
    for item in items.try_iter()? {
        let item=item?;
        if scene.commands.len()>=COMMAND_LIMIT{return Err(invalid("compiler command count exceeded"));}
        let name:String=item.get_type().name()?.extract()?;
        let path=matches!(name.as_str(),"VectorPath"|"ClipPush"|"ClipStrokePush"|"VectorLinearGradient"|"VectorRadialGradient");
        let mut transform=IDENTITY;let mut bounds=None;let mut resource=0;let mut axis_clip=None;
        if path {
            transform=matrix(&item)?;
            let commands=item.getattr("commands")?;
            let bytes=if let Ok(value)=commands.getattr("data") {value.cast_into::<PyBytes>()?}
                else {super::encode_commands(py,commands.cast::<PyTuple>()?)?};
            validate_path(bytes.as_bytes())?;
            bounds=packed_bounds(bytes.as_bytes(),transform)?;
            if name=="ClipPush"{axis_clip=axis_rectangle(bytes.as_bytes(),&transform);}
            if bytes.as_bytes().len()>LIMIT{return Err(invalid("compiler path budget exceeded"));}
            resource=scene.intern(Resource::Path(bytes.as_bytes().to_vec()),&mut index)?;
        }
        let op=match name.as_str() {
            "VectorPath"=>{
                let fill=item.getattr("fill_argb")?.extract()?;let stroke_argb:Option<u32>=item.getattr("stroke_argb")?.extract()?;
                let width=item.getattr("stroke_width")?.extract()?;finite(&[width])?;
                // Native stroking can extend through miter/cap geometry. Do not cull it yet.
                if stroke_argb.is_some(){bounds=None;}
                let groupable=item.getattr("groupable")?.extract()?;
                Operation::Path{resource,fill,stroke:stroke_argb,width,style:stroke(&item)?,even_odd:item.getattr("even_odd")?.extract()?,groupable,shading:item.getattr("shading")?.extract()?,instanced:groupable&&!item.getattr("transform")?.is_none()}
            },
            "ClipPush"=>Operation::Clip{resource,even_odd:item.getattr("even_odd")?.extract()?},
            "ClipStrokePush"=>{
                let width=item.getattr("stroke_width")?.extract()?;finite(&[width])?;
                bounds=None;Operation::StrokeClip{resource,width,style:stroke(&item)?}
            },
            "VectorImage"=>{
                transform=matrix(&item)?;
                let pixels=item.getattr("pixels")?;let pixels=pixels.cast::<PyBytes>()?;
                let width:u32=item.getattr("width")?.extract()?;let height:u32=item.getattr("height")?.extract()?;let stride:u32=item.getattr("stride")?.extract()?;
                let needed=(height as usize).checked_mul(stride as usize).ok_or_else(||invalid("image size overflow"))?;
                if width==0||height==0||(stride as u64)<width as u64*4||needed!=pixels.as_bytes().len(){return Err(invalid("invalid compiler image layout"));}
                if needed>IMAGE_LIMIT{return Err(invalid("compiler image budget exceeded"));}
                resource=scene.intern(Resource::Image{pixels:pixels.as_bytes().to_vec(),width,height,stride},&mut index)?;
                Operation::Image{resource,opacity:opacity(&item)?,interpolate:item.getattr("interpolate")?.extract()?}
            },
            "VectorLinearGradient"=>{
                let start:[f64;2]=item.getattr("start")?.extract()?;let end:[f64;2]=item.getattr("end")?.extract()?;
                finite(&start)?;finite(&end)?;
                Operation::Linear{resource,start,end,stops:stops(&item)?,even_odd:item.getattr("even_odd")?.extract()?}
            },
            "VectorRadialGradient"=>{
                let center:[f64;2]=item.getattr("center")?.extract()?;let origin:[f64;2]=item.getattr("origin")?.extract()?;let radius:[f64;2]=item.getattr("radius")?.extract()?;
                finite(&center)?;finite(&origin)?;finite(&radius)?;
                Operation::Radial{resource,center,origin,radius,stops:stops(&item)?,even_odd:item.getattr("even_odd")?.extract()?}
            },
            "GroupPush"=>Operation::Group{opacity:opacity(&item)?,blend:item.getattr("blend_mode")?.extract()?,isolated:item.getattr("isolated")?.extract()?,knockout:item.getattr("knockout")?.extract()?},
            "GroupPop"=>Operation::GroupEnd,
            "MaskBegin"=>{
                let area:Rect=item.getattr("area")?.extract()?;finite(&area)?;
                Operation::Mask{area,luminosity:item.getattr("luminosity")?.extract()?,background:item.getattr("background_argb")?.extract()?}
            },
            "MaskEnd"=>{let transfer:Vec<f64>=item.getattr("transfer")?.extract()?;finite(&transfer)?;if transfer.len()>65536{return Err(invalid("transfer table too large"));}Operation::MaskEnd{transfer}},
            "ClipPop"=>Operation::ClipEnd,
            _=>return Err(invalid("unknown Rust compiler operation")),
        };
        scene.commands.push(Command{op,matrix:transform,bounds,scope_end:None,capture_end:None,complex_depth:0,native_opcode:0,axis_clip});
    }
    Ok(scene)
}

#[cfg_attr(feature="python",pyclass(frozen,module="pdfeditor._path_packer"))]
pub struct RustCompiledScene {scene:Scene,source_count:usize}

#[cfg(feature="python")]
#[pymethods]
impl RustCompiledScene {
    #[getter] fn command_count(&self)->usize{self.scene.commands.len()}
    #[getter] fn source_command_count(&self)->usize{self.source_count}
    #[getter] fn resource_count(&self)->usize{self.scene.resources.len()}
    #[getter] fn resource_bytes(&self)->usize{self.scene.resource_bytes}
    #[getter] fn image_bytes(&self)->usize{self.scene.image_bytes}
    #[getter] fn features(&self)->Vec<String>{self.feature_names()}
    #[getter] fn requires_luminosity(&self)->bool {
        self.scene.commands.iter().any(|command|matches!(command.op,Operation::Mask{luminosity:true,..}))
    }
    fn to_bytes<'py>(&self,py:Python<'py>)->CompileResult<Bound<'py,PyBytes>> {
        let options=bincode::DefaultOptions::new().with_fixint_encoding().with_little_endian().with_limit(512*1024*1024);
        let size=py.detach(||options.serialized_size(&self.scene))
            .map_err(|error|invalid(&error.to_string()))?;
        let size=usize::try_from(size).map_err(|_|invalid("compiler packet size overflow"))?;
        PyBytes::new_with(py,size+8,|packet| {
            packet[..8].copy_from_slice(b"LFSC\x03\0\0\0");
            let mut target=&mut packet[8..];
            py.detach(||options.serialize_into(&mut target,&self.scene))
                .map_err(|error|invalid(&error.to_string()))
        })
    }
    fn scope_plan(&self)->Vec<(Option<u32>,Option<u32>,u32)> {
        self.scene.commands.iter().map(|command|(command.scope_end,command.capture_end,command.complex_depth)).collect()
    }
    fn viewport_plan(&self,rect:Rect,padding:f64)->CompileResult<Vec<u32>> {
        finite(&rect)?;
        if rect[2]<rect[0]||rect[3]<rect[1]||!padding.is_finite()||padding<0.{return Err(invalid("invalid viewport"));}
        let mut result=Vec::new();
        for (index,command) in self.scene.commands.iter().enumerate() {
            let drawable=matches!(command.op,Operation::Path{..}|Operation::Image{..}|Operation::Linear{..}|Operation::Radial{..}|Operation::GeometryGroup{..});
            let visible=command.bounds.map_or(true,|b|b[2]+padding>=rect[0]&&b[0]-padding<=rect[2]&&b[3]+padding>=rect[1]&&b[1]-padding<=rect[3]);
            if !drawable||command.complex_depth>0||visible {result.push(index as u32);}
        }
        Ok(result)
    }
}

#[cfg(feature="python")]
#[pyfunction]
pub fn compile_scene(py:Python<'_>,scene:&Bound<'_,PyAny>)->CompileResult<RustCompiledScene> {
    let owned=import_scene(py,scene)?;
    let source_count=owned.commands.len();
    let scene=py.detach(||owned.analyse())?;
    Ok(RustCompiledScene{scene,source_count})
}

// The standalone worker uses the same owned scene and serializer as the bindings.
impl RustCompiledScene {
    pub fn feature_names(&self)->Vec<String>{
        let mut features=vec!["rust-compiler".to_string()];
        if self.scene.image_bytes>0{features.push("image".into());}
        // Full-size JPEG sources need no new preparation at higher zoom.
        // Raw raster regions have no such guarantee and retain refinement.
        if self.scene.resources.iter().any(|r|match r {
            Resource::Image{..}=>true,
            Resource::Jpeg{width,height,target_width,target_height,..}=>target_width<width||target_height<height,
            _=>false,
        }){features.push("image-downsample".into());}
        if self.scene.resources.iter().any(|r|matches!(r,Resource::Jpeg{..})){features.push("jpeg-ycbcr".into());}
        if self.scene.commands.iter().any(|c|matches!(c.op,Operation::Mesh{..})){features.push("vector-mesh".into());}
        if self.scene.commands.iter().any(|c|matches!(c.op,Operation::Mask{..})){features.push("gpu-mask".into());}
        if self.scene.commands.iter().any(|c|matches!(c.op,Operation::Mask{luminosity:true,..})){features.push("gpu-luminosity".into());}
        if self.scene.commands.iter().any(|c|matches!(c.op,Operation::CoverageBegin)){features.push("gpu-backdrop".into());}
        if self.scene.preparation&0x8000!=0{features.push("rgb-transparency-approximation".into());}
        if self.scene.commands.iter().any(|c|matches!(c.op,Operation::Linear{..}|Operation::Radial{..})){
            features.extend(["shading".into(),"vector-shading".into(),"gradient-primitive".into()]);
        }
        for (flag,names) in [(0x100,&["raster-shading"][..]),(0x200,&["cpu-island"][..]),
            (0x400,&["clip-mask"][..]),(0x800,&["alpha-image-fusion"][..]),
            (0x1000,&["text-raster-fallback"][..]),(0x2000,&["stencil"][..]),
            (0x4000,&["raster-pattern"][..])]{
            if self.scene.preparation&flag!=0{features.extend(names.iter().map(|s|s.to_string()));}
        }features
    }
    pub fn commands_len(&self)->usize{self.scene.commands.len()}
    pub fn images_bytes(&self)->usize{self.scene.image_bytes}
    pub fn packet(&self)->CompileResult<Vec<u8>>{
        let options=bincode::DefaultOptions::new().with_fixint_encoding().with_little_endian().with_limit(512*1024*1024);
        let size=options.serialized_size(&self.scene).map_err(|e|invalid(&e.to_string()))? as usize;
        if size>512*1024*1024-8{return Err(invalid("compiler packet byte budget exceeded"));}
        let mut bytes=Vec::with_capacity(size+8);bytes.extend_from_slice(b"LFSC\x03\0\0\0");
        options.serialize_into(&mut bytes,&self.scene).map_err(|e|invalid(&e.to_string()))?;Ok(bytes)
    }
}
fn packed_bounds(data:&[u8],m:Matrix)->CompileResult<Option<Rect>>{
    validate_path(data)?;let mut at=0;let mut bounds:Option<Rect>=None;
    while at<data.len(){let n=match data[at]{1|2=>2,3=>6,_=>0};at+=1;
        for _ in (0..n).step_by(2){
            let x=f64::from_le_bytes(data[at..at+8].try_into().unwrap());
            let y=f64::from_le_bytes(data[at+8..at+16].try_into().unwrap());at+=16;
            let px=m[0]*x+m[2]*y+m[4];let py=m[1]*x+m[3]*y+m[5];finite(&[px,py])?;
            if let Some(b)=&mut bounds{if px<b[0]{b[0]=px;}if py<b[1]{b[1]=py;}if px>b[2]{b[2]=px;}if py>b[3]{b[3]=py;}}
            else{bounds=Some([px,py,px,py]);}
        }
    }Ok(bounds)
}
