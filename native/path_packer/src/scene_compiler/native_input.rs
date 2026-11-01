//! Direct MuPDF event input, scope policy and resource normalization.
//! No Python scene objects, path tuples, glyph loops or region decisions.
use super::*;

struct Reader<'a>{data:&'a [u8],at:usize}
impl<'a> Reader<'a>{
    fn take(&mut self,n:usize)->CompileResult<&'a [u8]>{
        if n>self.data.len()-self.at{return Err(invalid("truncated native scene input"));}
        let p=&self.data[self.at..self.at+n];self.at+=n;Ok(p)
    }
    fn u32(&mut self)->CompileResult<u32>{Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))}
    fn u64(&mut self)->CompileResult<usize>{usize::try_from(u64::from_le_bytes(self.take(8)?.try_into().unwrap())).map_err(|_|invalid("native input overflow"))}
    fn number(&mut self)->CompileResult<f64>{let x=f64::from_le_bytes(self.take(8)?.try_into().unwrap());finite(&[x])?;Ok(x)}
    fn rect(&mut self)->CompileResult<Rect>{Ok([self.number()?,self.number()?,self.number()?,self.number()?])}
    fn matrix(&mut self)->CompileResult<Matrix>{Ok([self.number()?,self.number()?,self.number()?,self.number()?,self.number()?,self.number()?])}
    fn done(&self)->CompileResult<()>{if self.at!=self.data.len(){Err(invalid("trailing native input"))}else{Ok(())}}
}
struct Raw{kind:u32,flags:u32,area:Rect,alpha:f64,end:usize,capture:usize,density:f64}
fn intersect(a:Rect,b:Rect)->Rect {
    let x=a[0].max(b[0]);let y=a[1].max(b[1]);[x,y,a[2].min(b[2]).max(x),a[3].min(b[3]).max(y)]
}
fn area(r:Rect)->f64{(r[2]-r[0]).max(0.)*(r[3]-r[1]).max(0.)}
fn request(out:&mut Vec<u8>,mode:u32,start:usize,end:usize,rect:Rect,scale:f64){
    for x in [mode,start as u32,end as u32,0]{out.extend_from_slice(&x.to_le_bytes());}
    for x in rect.into_iter().chain([scale]){out.extend_from_slice(&x.to_le_bytes());}
}

pub fn plan(metadata:&[u8],page:Rect,scale:f64,viewport:Option<Rect>)->CompileResult<Vec<u8>>{
    finite(&page)?;if area(page)<=0.||!scale.is_finite()||scale<=0.||scale>64.{return Err(invalid("invalid native page scale"));}
    let view=viewport.unwrap_or(page);finite(&view)?;
    if view[2]<view[0]||view[3]<view[1]{return Err(invalid("invalid native viewport"));}
    if metadata.len()%48!=0||metadata.len()/48>COMMAND_LIMIT{return Err(invalid("invalid native metadata size"));}
    let build=||->CompileResult<Vec<u8>>{
        let mut reader=Reader{data:metadata,at:0};let mut raw=Vec::new();let mut scopes=Vec::new();
        while reader.at<metadata.len(){
            let kind=reader.u32()?;let flags=reader.u32()?;let area=reader.rect()?;let alpha=reader.number()?;
            if kind>20||!(0.0..=1.0).contains(&alpha){return Err(invalid("invalid native operation"));}
            let density=if matches!(kind,9..=11){
                ((flags&65535) as f64/(area[2]-area[0]).max(1e-9)).max((flags>>16) as f64/(area[3]-area[1]).max(1e-9))
            }else{64.};
            let i=raw.len();raw.push(Raw{kind,flags,area,alpha,end:i,capture:i,density});
            match kind {
                2|3|6|7|11=>scopes.push((1,i)),13=>scopes.push((2,i)),15=>scopes.push((3,i)),17=>scopes.push((4,i)),
                14=>{let scope=scopes.last_mut().ok_or_else(||invalid("native mask underflow"))?;
                    if scope.0!=2{return Err(invalid("native crossed mask"));}raw[scope.1].capture=i;scope.0=1;},
                12|16|18=>{let expected=if kind==12{1}else if kind==16{3}else{4};
                    let (k,start)=scopes.pop().ok_or_else(||invalid("native scope underflow"))?;
                    if k!=expected{return Err(invalid("native crossed scope"));}raw[start].end=i;},_=>{}
            }
            if scopes.len()>DEPTH_LIMIT{return Err(invalid("native scope depth exceeded"));}
        }
        if !scopes.is_empty(){return Err(invalid("native unclosed scope"));}
        // Clip extents bound image allocation, including huge source images
        // exposed through a tiny Illustrator clipping path.
        let mut bounds=page;let mut stack=Vec::new();
        for r in &mut raw {
            match r.kind {
                2|3|6|7|11|13|15|17=>{stack.push(bounds);bounds=intersect(bounds,r.area);},
                12|16|18=>{bounds=stack.pop().ok_or_else(||invalid("native extent underflow"))?;},_=>{}
            }
            if matches!(r.kind,0..=11|13|15|17){r.area=intersect(r.area,bounds);}
        }
        let mut jobs=Vec::new();let mut i=0;let mut regions=0;
        while i<raw.len(){
            let r=&raw[i];let mut mode=0;let mut end=i;let mut rect=intersect(intersect(r.area,page),view);
            let mut density=(scale*if matches!(r.kind,9..=11){1.}else{2.}).min(64.).min(r.density.max(0.01));
            match r.kind {
                13=>{
                    // A whole alpha-image scope has no backdrop-dependent ink.
                    let content=&raw[r.capture+1..r.end];
                    let image_only=content.iter().filter(|x|x.kind!=19&&x.kind!=20).count()==1&&content.iter().any(|x|x.kind==9||x.kind==10);
                    mode=if image_only{1}else{2};end=if image_only{r.end}else{r.capture};
                },
                11=>{
                    let content=&raw[i+1..r.end];
                    let image=content.iter().find(|x|matches!(x.kind,9|10));
                    if content.iter().filter(|x|x.kind!=19&&x.kind!=20).count()==1&&image.is_some(){
                        mode=6;end=r.end;density=scale.min(64.).min(r.density.max(image.unwrap().density).max(0.01));
                    }else{mode=3;}
                },
                8=>{if r.flags!=2&&r.flags!=3{mode=1;density=scale;}},9|10=>{mode=5;},
                17=>{mode=1;end=r.end;},
                15=>{
                    if r.flags&16!=0&&(r.alpha<1.-1e-6||r.flags>>8!=0){
                        return Err(invalid("unsupported CMYK transparency group"));
                    }
                    let content=&raw[i+1..r.end];
                    let region=r.flags&2!=0&&r.flags>>8==0&&r.alpha==1.&&r.end-i>=128&&r.end-i<=65536&&area(r.area)<=area(page)*0.005&&regions<64
                        &&!content.iter().any(|x|matches!(x.kind,4..=7|17));
                    if region {mode=1;end=r.end;regions+=1;}
                    else if r.flags>>8!=0&&r.flags&1==0{
                        let ink:Vec<_>=content.iter().filter(|x|matches!(x.kind,0|1|4|5|8|9|10)).collect();
                        let opaque=ink.iter().all(|x|matches!(x.kind,0|1|4|5)&&x.alpha==1.);
                        let shading=ink.iter().all(|x|x.kind==8);
                        if ink.len()!=1&&!opaque&&!shading{return Err(invalid("unsupported nonisolated blend group"));}
                    }
                },
                _=>{}
            }
            if mode!=0{
                // Keep antialiased boundary pixels and round dimensions conservatively.
                if area(rect)>0.{let pad=1./density;rect=intersect([rect[0]-pad,rect[1]-pad,rect[2]+pad,rect[3]+pad],view);}
                let cap=(16*1024*1024/4) as f64;
                if area(rect)>0.{density=density.min((cap/area(rect)).sqrt()*0.98);
                    density=density.min(32760./(rect[2]-rect[0]).max(rect[3]-rect[1]));}
                if density<=0.||!density.is_finite(){return Err(invalid("native raster density exhausted"));}
            }
            jobs.push((mode,i,end,rect,density));i=end+1;
        }
        // Allocate the complete raster working set together, rather than letting
        // the first large image consume the budget reserved for later masks.
        let desired:f64=jobs.iter().filter(|j|j.0!=0).map(|j|{
            ((j.3[2]-j.3[0])*j.4+2.)*((j.3[3]-j.3[1])*j.4+2.)*4.
        }).sum();
        let factor=if desired>IMAGE_LIMIT as f64*0.9{(IMAGE_LIMIT as f64*0.9/desired).sqrt()}else{1.};
        let mut out=Vec::new();let mut total=0usize;
        for (mode,start,end,rect,density) in jobs{
            let density=if mode!=0{density*factor}else{density};
            if mode!=0&&area(rect)>0.{
                let w=((rect[2]*density).ceil()-(rect[0]*density).floor()).max(0.);
                let h=((rect[3]*density).ceil()-(rect[1]*density).floor()).max(0.);
                total=total.checked_add((w*h*4.) as usize).ok_or_else(||invalid("native raster overflow"))?;
                if total>IMAGE_LIMIT{return Err(invalid("native raster resource budget exceeded"));}
            }
            request(&mut out,mode,start,end,rect,density);
        }
        Ok(out)
    };
    build()
}

fn argb(values:[f64;4])->u32{
    let c=values.map(|v|(v*255.).round_ties_even().clamp(0.,255.) as u32);
    (c[3]<<24)|(c[0]<<16)|(c[1]<<8)|c[2]
}
fn path_segment(path:&mut Vec<u8>,tag:u8,points:&[[f64;2]]){
    path.push(tag);for p in points{for value in p{path.extend_from_slice(&value.to_le_bytes());}}
}
fn polygon(points:&[[f64;2]])->Vec<u8>{
    let mut p=Vec::new();for (i,point) in points.iter().enumerate(){path_segment(&mut p,if i==0{1}else{2},&[*point]);}p.push(4);p
}
fn push(scene:&mut Scene,op:Operation,bounds:Option<Rect>,axis_clip:Option<Rect>){
    scene.commands.push(Command{op,matrix:IDENTITY,bounds,axis_clip,scope_end:None,capture_end:None,complex_depth:0,native_opcode:0});
}
fn gradient_input(p:&mut Reader<'_>,scene:&mut Scene,index:&mut HashMap<u64,Vec<u32>>)->CompileResult<()>{
    let kind=p.u32()?;let m=p.matrix()?;let b=p.rect()?;
    let coords=[p.number()?,p.number()?,p.number()?,p.number()?,p.number()?,p.number()?];
    let extend=[p.u32()?!=0,p.u32()?!=0];let mut lut=Vec::with_capacity(256);
    for _ in 0..256{lut.push(argb(p.rect()?));}p.done()?;
    if area(b)<=0.{return Ok(());}
    let point=|x:f64,y:f64|[x*m[0]+y*m[2]+m[4],x*m[1]+y*m[3]+m[5]];
    let stops=(0..=64).map(|i|{let t=i as f64/64.;(t,lut[(t*255.).round_ties_even() as usize])}).collect();
    let start=point(coords[0],coords[1]);let end=point(coords[3],coords[4]);
    let (path,radial)=if kind==2{
        let dx=end[0]-start[0];let dy=end[1]-start[1];let length=dx.hypot(dy);
        if length<=1e-6{return Err(invalid("degenerate native linear gradient"));}
        let u=[dx/length,dy/length];let v=[-u[1],u[0]];
        let corners=[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]]];
        let t:Vec<_>=corners.iter().map(|p|((p[0]-start[0])*u[0]+(p[1]-start[1])*u[1])/length).collect();
        let mut lower=t.iter().copied().fold(f64::INFINITY,f64::min);let mut upper=t.iter().copied().fold(f64::NEG_INFINITY,f64::max);
        if !extend[0]{lower=lower.max(0.);}if !extend[1]{upper=upper.min(1.);}if upper<=lower{return Ok(());}
        let reach=(b[2]-b[0]).hypot(b[3]-b[1])+length+4.;
        let c0=[start[0]+u[0]*length*lower,start[1]+u[1]*length*lower];
        let c1=[start[0]+u[0]*length*upper,start[1]+u[1]*length*upper];
        (polygon(&[[c0[0]+v[0]*reach,c0[1]+v[1]*reach],[c1[0]+v[0]*reach,c1[1]+v[1]*reach],
                  [c1[0]-v[0]*reach,c1[1]-v[1]*reach],[c0[0]-v[0]*reach,c0[1]-v[1]*reach]]),None)
    }else if kind==3{
        let r=coords[5];if coords[2].abs()>1e-6||r<=1e-6{return Err(invalid("unsupported radial start radius"));}
        let c=end;let px=point(coords[3]+r,coords[4]);let py=point(coords[3],coords[4]+r);
        let x=[px[0]-c[0],px[1]-c[1]];let y=[py[0]-c[0],py[1]-c[1]];
        let at=|a:f64,b:f64|[c[0]+x[0]*a+y[0]*b,c[1]+x[1]*a+y[1]*b];
        let k=0.5522847498307936;let mut path=Vec::new();path_segment(&mut path,1,&[at(1.,0.)]);
        for controls in [[at(1.,k),at(k,1.),at(0.,1.)],[at(-k,1.),at(-1.,k),at(-1.,0.)],
                         [at(-1.,-k),at(-k,-1.),at(0.,-1.)],[at(k,-1.),at(1.,-k),at(1.,0.)]]{
            path_segment(&mut path,3,&controls);
        }path.push(4);(path,Some([x[0].hypot(x[1]),y[0].hypot(y[1])]))
    }else{return Err(invalid("unknown native gradient"));};
    validate_path(&path)?;
    let clip=polygon(&[[b[0],b[1]],[b[2],b[1]],[b[2],b[3]],[b[0],b[3]]]);
    let clip=scene.intern(Resource::Path(clip),index)?;
    let resource=scene.intern(Resource::Path(path),index)?;
    push(scene,Operation::Clip{resource:clip,even_odd:false},Some(b),Some(b));
    let op=if let Some(radius)=radial{Operation::Radial{resource,center:end,origin:start,radius,stops,even_odd:false}}
        else{Operation::Linear{resource,start,end,stops,even_odd:false}};
    push(scene,op,Some(b),None);push(scene,Operation::ClipEnd,None,None);Ok(())
}
fn import_native(data:&[u8])->CompileResult<Scene>{
    if data.len()>256*1024*1024{return Err(invalid("native input byte budget exceeded"));}
    let mut reader=Reader{data,at:0};let mut scene=Scene::new();let mut index=HashMap::new();
    while reader.at<data.len(){
        if scene.commands.len()>=COMMAND_LIMIT{return Err(invalid("native output count exceeded"));}
        let kind=reader.u32()?;let len=reader.u64()?;let mut p=Reader{data:reader.take(len)?,at:0};
        let mut matrix=IDENTITY;let mut bounds=None;let mut axis_clip=None;
        let op=match kind{
            8=>{gradient_input(&mut p,&mut scene,&mut index)?;continue;},
            0..=3=>{
                matrix=p.matrix()?;let even_odd=p.u32()?!=0;let groupable=p.u32()?!=0;
                let color=argb(p.rect()?);let mut width=0.;let mut style=None;
                if kind==1||kind==3{
                    let start=p.u32()?;let dash=p.u32()?;let end=p.u32()?;let join=p.u32()?;
                    width=p.number()?;let miter=p.number()?;let mut phase=p.number()?;let n=p.u32()? as usize;
                    if n>4096||width<0.||miter<0.||start>3||dash>3||end>3||join>3{return Err(invalid("invalid native stroke"));}
                    let mut dashes=Vec::with_capacity(n);
                    for _ in 0..n{let v=p.number()?;if v<0.{return Err(invalid("negative native dash"));}dashes.push(v);}
                    if n>0{if width<=0.{return Err(invalid("unsupported dashed hairline"));}phase/=width;for v in &mut dashes{*v/=width;}}
                    style=Some(Stroke{start,dash,end,join,miter,phase,dashes});
                }
                let n=p.u64()?;let bytes=p.take(n)?;validate_path(bytes)?;
                if bytes.is_empty()&&kind<2{p.done()?;continue;}
                if kind==0||kind==2{bounds=packed_bounds(bytes,matrix)?;}
                if kind==2{axis_clip=axis_rectangle(bytes,&matrix);}
                let owned=if bytes.is_empty(){let mut v=vec![1];v.extend_from_slice(&[0;16]);v.push(4);v}else{bytes.to_vec()};
                let resource=scene.intern(Resource::Path(owned),&mut index)?;
                match kind{
                    0|1=>Operation::Path{resource,fill:if kind==0{Some(color)}else{None},stroke:if kind==1{Some(color)}else{None},width,style,even_odd,groupable,shading:false,instanced:groupable},
                    2=>Operation::Clip{resource,even_odd},_=>Operation::StrokeClip{resource,width,style}
                }
            },
            9=>{
                matrix=p.matrix()?;let width=p.u32()?;let height=p.u32()?;let stride=p.u32()?;
                // Smooth continuous-tone images; retain nearest sampling for
                // binary/stencil art unless the PDF explicitly requests it.
                let flags=p.u32()?;let interpolate=flags&3!=0;
                scene.preparation|=flags&0x7f00;
                let size=(height as usize).checked_mul(stride as usize).ok_or_else(||invalid("native image overflow"))?;
                if width==0||height==0||stride as u64!=width as u64*4||size>IMAGE_LIMIT{return Err(invalid("invalid native image"));}
                let rgba=p.take(size)?;let mut pixels=rgba.to_vec();
                for px in pixels.chunks_exact_mut(4){px.swap(0,2);}
                let resource=scene.intern(Resource::Image{pixels,width,height,stride},&mut index)?;
                Operation::Image{resource,opacity:1.,interpolate}
            },
            12=>Operation::ClipEnd,
            13=>Operation::Mask{area:p.rect()?,luminosity:false,background:0},
            14=>Operation::MaskEnd{transfer:Vec::new()},
            15=>{let opacity=p.number()?;let blend=p.u32()?;let mut isolated=p.u32()?!=0;let knockout=p.u32()?!=0;
                if !(0.0..=1.0).contains(&opacity)||blend>15{return Err(invalid("invalid native group"));}
                // Single-ink blend sources can be isolated; normal knockout
                // groups retain the existing accepted isolation approximation.
                if blend!=0||knockout{isolated=true;}
                Operation::Group{opacity,blend,isolated,knockout}},
            16=>Operation::GroupEnd,_=>return Err(invalid("unknown materialized operation"))
        };
        p.done()?;scene.commands.push(Command{op,matrix,bounds,axis_clip,scope_end:None,capture_end:None,complex_depth:0,native_opcode:0});
    }
    Ok(scene)
}
pub fn compile(data:&[u8])->CompileResult<RustCompiledScene>{
    let owned=import_native(data)?;let source_count=owned.commands.len();
    let scene=owned.analyse()?;Ok(RustCompiledScene{scene,source_count})
}
#[cfg(feature="python")]
#[pyfunction]
#[pyo3(signature=(metadata,page,scale=1.,viewport=None))]
pub fn plan_native_scene<'py>(py:Python<'py>,metadata:&[u8],page:Rect,scale:f64,viewport:Option<Rect>)->CompileResult<Bound<'py,PyBytes>>{
    let bytes=py.detach(||plan(metadata,page,scale,viewport))?;Ok(PyBytes::new(py,&bytes))
}
#[cfg(feature="python")]
#[pyfunction]
pub fn compile_native_scene(py:Python<'_>,data:&[u8])->CompileResult<RustCompiledScene>{
    py.detach(||compile(data))
}
