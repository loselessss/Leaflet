// MuPDF SDK adapter only. Scope selection and GPU compilation live in Rust.
#include <algorithm>
#include <cmath>
#include <memory>
#include <stdexcept>
#include <map>
#include <chrono>

namespace leaflet_scene {
thread_local std::string error;
constexpr size_t budget=512u*1024*1024;
const fz_matrix identity={1,0,0,1,0,0};
constexpr fz_color_params default_params={1,1,0,0};
struct Record {
    uint32_t kind=0,flags=0;
    fz_path* path=nullptr; fz_text* text=nullptr; fz_stroke_state* stroke=nullptr;
    fz_image* image=nullptr; fz_shade* shade=nullptr; fz_colorspace* cs=nullptr;
    fz_default_colorspaces* defaults=nullptr; fz_function* function=nullptr;
    fz_matrix matrix=identity; fz_rect area={},scissor={},view={};
    fz_color_params params=default_params;
    float color[FZ_MAX_COLORS]={},alpha=1,xstep=0,ystep=0;
    int isolated=1,knockout=0,blend=0,id=0,doc_id=0,set=0,clear=0;
    bool raster_text=false;
    ~Record() {
        mupdf::ll_fz_drop_path(path);mupdf::ll_fz_drop_text(text);
        mupdf::ll_fz_drop_stroke_state(stroke);mupdf::ll_fz_drop_image(image);
        mupdf::ll_fz_drop_shade(shade);mupdf::ll_fz_drop_colorspace(cs);
        mupdf::ll_fz_drop_default_colorspaces(defaults);mupdf::ll_fz_drop_function(function);
    }
};
struct GlyphOutline {Result path;bool even_odd=false;};
struct Job {std::vector<std::unique_ptr<Record>> records;Result metadata;bool failed=false;fz_rect page;
    fz_document* owned_document=nullptr;fz_page* owned_page=nullptr;
    std::map<std::pair<fz_font*,int>,GlyphOutline> glyphs;size_t glyph_bytes=0;
    size_t record_limit=1048576;
    fz_cookie cookie={};bool count_only=false;uint64_t score=0,operations=0;
    std::chrono::steady_clock::time_point deadline=std::chrono::steady_clock::time_point::max();
    ~Job(){records.clear();mupdf::ll_fz_drop_page(owned_page);mupdf::ll_fz_drop_document(owned_document);}};
struct Device {fz_device super;Job* job;};
template<class T> void put(Result& out,const T& value) {
    if(out.bytes.size()+sizeof(T)>budget) throw std::runtime_error("native scene budget exceeded");
    auto* p=reinterpret_cast<const unsigned char*>(&value);out.bytes.insert(out.bytes.end(),p,p+sizeof(T));
}
void blob(Result& out,const unsigned char* p,size_t n) {
    if(n>budget-out.bytes.size())throw std::runtime_error("native scene budget exceeded");
    out.bytes.insert(out.bytes.end(),p,p+n);
}
void rect(Result& out,fz_rect r) {for(float x:{r.x0,r.y0,r.x1,r.y1})put(out,double(x));}
void matrix(Result& out,fz_matrix m) {for(float x:{m.a,m.b,m.c,m.d,m.e,m.f})put(out,double(x));}
void color(Record& r,fz_colorspace* cs,const float* c,float a,fz_color_params p) {
    r.cs=mupdf::ll_fz_keep_colorspace(cs);r.alpha=a;r.params=p;
    const int n=cs?mupdf::ll_fz_colorspace_n(cs):0;
    if(n<0||n>FZ_MAX_COLORS)throw std::runtime_error("invalid native color");
    if(c)std::copy(c,c+n,r.color);
}
template<class F> void capture(fz_device* d,uint32_t k,F f) noexcept {
    Job& job=*reinterpret_cast<Device*>(d)->job;if(job.failed)return;
    if(job.count_only){if(k<=18){++job.operations;job.score+=(k>=4&&k<=8)||k==13||k==15||k==17?8:k>=9&&k<=11?4:1;}return;}
    try {
        if((job.records.size()&63)==0&&std::chrono::steady_clock::now()>=job.deadline)throw std::runtime_error("GPU scene time budget exceeded");
        if(job.records.size()>=job.record_limit||job.records.size()>256*1024*1024/sizeof(Record))throw std::runtime_error("native command budget exceeded");
        auto r=std::make_unique<Record>();r->kind=k;f(*r);
        job.records.push_back(std::move(r));
    }catch(const std::exception& e){error=e.what();job.failed=true;job.cookie.abort=1;}catch(...){error="native capture failure";job.failed=true;job.cookie.abort=1;}
}
#define CB(name,args,kind,...) static void name args noexcept {capture(d,kind,[&](Record& r){__VA_ARGS__;});}
CB(fill_path,(fz_context*,fz_device* d,const fz_path* p,int eo,fz_matrix m,fz_colorspace* cs,const float* c,float a,fz_color_params cp),0,
    r.path=mupdf::ll_fz_keep_path(p);r.flags=eo;r.matrix=m;color(r,cs,c,a,cp);r.area=mupdf::ll_fz_bound_path(p,nullptr,m))
CB(stroke_path,(fz_context*,fz_device* d,const fz_path* p,const fz_stroke_state* s,fz_matrix m,fz_colorspace* cs,const float* c,float a,fz_color_params cp),1,
    r.path=mupdf::ll_fz_keep_path(p);r.stroke=mupdf::ll_fz_keep_stroke_state(s);r.matrix=m;color(r,cs,c,a,cp);r.area=mupdf::ll_fz_bound_path(p,s,m))
CB(clip_path,(fz_context*,fz_device* d,const fz_path* p,int eo,fz_matrix m,fz_rect sc),2,
    r.path=mupdf::ll_fz_keep_path(p);r.flags=eo;r.matrix=m;r.scissor=sc;r.area=mupdf::ll_fz_bound_path(p,nullptr,m))
CB(clip_stroke_path,(fz_context*,fz_device* d,const fz_path* p,const fz_stroke_state* s,fz_matrix m,fz_rect sc),3,
    r.path=mupdf::ll_fz_keep_path(p);r.stroke=mupdf::ll_fz_keep_stroke_state(s);r.matrix=m;r.scissor=sc;r.area=mupdf::ll_fz_bound_path(p,s,m))
CB(fill_text,(fz_context*,fz_device* d,const fz_text* t,fz_matrix m,fz_colorspace* cs,const float* c,float a,fz_color_params cp),4,
    r.text=mupdf::ll_fz_keep_text(t);r.matrix=m;color(r,cs,c,a,cp);r.area=mupdf::ll_fz_bound_text(t,nullptr,m))
CB(stroke_text,(fz_context*,fz_device* d,const fz_text* t,const fz_stroke_state* s,fz_matrix m,fz_colorspace* cs,const float* c,float a,fz_color_params cp),5,
    r.text=mupdf::ll_fz_keep_text(t);r.stroke=mupdf::ll_fz_keep_stroke_state(s);r.matrix=m;color(r,cs,c,a,cp);r.area=mupdf::ll_fz_bound_text(t,s,m))
CB(clip_text,(fz_context*,fz_device* d,const fz_text* t,fz_matrix m,fz_rect sc),6,
    r.text=mupdf::ll_fz_keep_text(t);r.matrix=m;r.scissor=sc;r.area=mupdf::ll_fz_bound_text(t,nullptr,m))
CB(clip_stroke_text,(fz_context*,fz_device* d,const fz_text* t,const fz_stroke_state* s,fz_matrix m,fz_rect sc),7,
    r.text=mupdf::ll_fz_keep_text(t);r.stroke=mupdf::ll_fz_keep_stroke_state(s);r.matrix=m;r.scissor=sc;r.area=mupdf::ll_fz_bound_text(t,s,m))
CB(fill_shade,(fz_context*,fz_device* d,fz_shade* s,fz_matrix m,float a,fz_color_params cp),8,
    r.shade=mupdf::ll_fz_keep_shade(s);r.matrix=m;r.alpha=a;r.params=cp;r.area=mupdf::ll_fz_bound_shade(s,m))
CB(fill_image,(fz_context*,fz_device* d,fz_image* i,fz_matrix m,float a,fz_color_params cp),9,
    r.image=mupdf::ll_fz_keep_image(i);r.matrix=m;r.alpha=a;r.params=cp;r.area=mupdf::ll_fz_transform_rect(fz_rect{0,0,1,1},m))
CB(fill_image_mask,(fz_context*,fz_device* d,fz_image* i,fz_matrix m,fz_colorspace* cs,const float* c,float a,fz_color_params cp),10,
    r.image=mupdf::ll_fz_keep_image(i);r.matrix=m;color(r,cs,c,a,cp);r.area=mupdf::ll_fz_transform_rect(fz_rect{0,0,1,1},m))
CB(clip_image_mask,(fz_context*,fz_device* d,fz_image* i,fz_matrix m,fz_rect sc),11,
    r.image=mupdf::ll_fz_keep_image(i);r.matrix=m;r.scissor=sc;r.area=mupdf::ll_fz_transform_rect(fz_rect{0,0,1,1},m))
CB(pop_clip,(fz_context*,fz_device* d),12,(void)r)
CB(begin_mask,(fz_context*,fz_device* d,fz_rect a,int lum,fz_colorspace* cs,const float* c,fz_color_params cp),13,
    r.area=a;r.flags=lum;color(r,cs,c,1,cp))
CB(end_mask,(fz_context*,fz_device* d,fz_function* fn),14,r.function=mupdf::ll_fz_keep_function(fn))
CB(begin_group,(fz_context*,fz_device* d,fz_rect a,fz_colorspace* cs,int iso,int ko,int blend,float alpha),15,
    r.area=a;r.cs=mupdf::ll_fz_keep_colorspace(cs);r.isolated=iso;r.knockout=ko;r.blend=blend;r.alpha=alpha;r.flags=uint32_t(iso)|(uint32_t(ko)<<1)|(uint32_t(blend)<<8)|(cs&&mupdf::ll_fz_colorspace_n(cs)==4?16u:0u))
CB(end_group,(fz_context*,fz_device* d),16,(void)r)
static int begin_tile(fz_context*,fz_device* d,fz_rect a,fz_rect v,float xs,float ys,fz_matrix m,int id,int docid) noexcept {
    capture(d,17,[&](Record& r){r.area=mupdf::ll_fz_transform_rect(a,m);r.scissor=a;r.view=v;r.xstep=xs;r.ystep=ys;r.matrix=m;r.id=id;r.doc_id=docid;});return 0;
}
CB(end_tile,(fz_context*,fz_device* d),18,(void)r)
CB(render_flags,(fz_context*,fz_device* d,int set,int clear),19,r.set=set;r.clear=clear)
CB(set_defaults,(fz_context*,fz_device* d,fz_default_colorspaces* cs),20,r.defaults=mupdf::ll_fz_keep_default_colorspaces(cs))
#undef CB
void dispatch(const Record& r,fz_device* d) {
    switch(r.kind) {
    case 0:mupdf::ll_fz_fill_path(d,r.path,int(r.flags),r.matrix,r.cs,r.color,r.alpha,r.params);break;
    case 1:mupdf::ll_fz_stroke_path(d,r.path,r.stroke,r.matrix,r.cs,r.color,r.alpha,r.params);break;
    case 2:mupdf::ll_fz_clip_path(d,r.path,int(r.flags),r.matrix,r.scissor);break;
    case 3:mupdf::ll_fz_clip_stroke_path(d,r.path,r.stroke,r.matrix,r.scissor);break;
    case 4:mupdf::ll_fz_fill_text(d,r.text,r.matrix,r.cs,r.color,r.alpha,r.params);break;
    case 5:mupdf::ll_fz_stroke_text(d,r.text,r.stroke,r.matrix,r.cs,r.color,r.alpha,r.params);break;
    case 6:mupdf::ll_fz_clip_text(d,r.text,r.matrix,r.scissor);break;
    case 7:mupdf::ll_fz_clip_stroke_text(d,r.text,r.stroke,r.matrix,r.scissor);break;
    case 8:mupdf::ll_fz_fill_shade(d,r.shade,r.matrix,r.alpha,r.params);break;
    case 9:mupdf::ll_fz_fill_image(d,r.image,r.matrix,r.alpha,r.params);break;
    case 10:mupdf::ll_fz_fill_image_mask(d,r.image,r.matrix,r.cs,r.color,r.alpha,r.params);break;
    case 11:mupdf::ll_fz_clip_image_mask(d,r.image,r.matrix,r.scissor);break;
    case 12:mupdf::ll_fz_pop_clip(d);break;
    case 13:mupdf::ll_fz_begin_mask(d,r.area,int(r.flags),r.cs,r.color,r.params);break;
    case 14:mupdf::ll_fz_end_mask_tr(d,r.function);break;
    case 15:mupdf::ll_fz_begin_group(d,r.area,r.cs,r.isolated,r.knockout,r.blend,r.alpha);break;
    case 16:mupdf::ll_fz_end_group(d);break;
    case 17:(void)mupdf::ll_fz_begin_tile_tid(d,r.scissor,r.view,r.xstep,r.ystep,r.matrix,r.id,r.doc_id);break;
    case 18:mupdf::ll_fz_end_tile(d);break;
    case 19:mupdf::ll_fz_render_flags(d,r.set,r.clear);break;
    case 20:mupdf::ll_fz_set_default_colorspaces(d,r.defaults);break;
    }
}
void event(Result& out,uint32_t kind,const Result& payload) {
    put(out,kind);put(out,uint64_t(payload.bytes.size()));blob(out,payload.bytes.data(),payload.bytes.size());++out.count;
}
void mask_begin_event(Result& out,fz_rect area,bool luminosity=false,uint32_t background=0) {
    Result p;rect(p,area);put(p,uint32_t(luminosity));put(p,background);event(out,13,p);
}
void mask_end_event(Result& out,fz_function* transfer=nullptr) {
    Result p;put(p,uint32_t(transfer?256:0));
    if(transfer)for(int i=0;i<256;++i){const float input=float(i)/255;float output=0;
        mupdf::ll_fz_eval_function(transfer,&input,1,&output,1);put(p,double(std::clamp(output,0.f,1.f)));}
    event(out,14,p);
}
Result path_bytes(const fz_path* p) {
    Result result;const fz_path_walker walker={move,line,cubic,close,nullptr,nullptr,nullptr,nullptr};
    mupdf::ll_fz_walk_path(p,&walker,&result);if(result.failed)throw std::runtime_error("native path budget");return result;
}
void path_event(Result& out,const Record& r,const Result& path,fz_matrix m,bool groupable=false) {
    Result payload;matrix(payload,m);put(payload,r.flags);put(payload,uint32_t(groupable));
    float rgb[3]={};if(r.cs)mupdf::ll_fz_convert_color(r.cs,r.color,mupdf::ll_fz_device_rgb(),rgb,nullptr,r.params);
    for(float x:rgb)put(payload,double(x));put(payload,double(r.alpha));
    if(r.stroke) {
        const auto& s=*r.stroke;for(int x:{int(s.start_cap),int(s.dash_cap),int(s.end_cap),int(s.linejoin)})put(payload,uint32_t(x));
        put(payload,double(s.linewidth));put(payload,double(s.miterlimit));put(payload,double(s.dash_phase));
        if(s.dash_len<0||s.dash_len>4096)throw std::runtime_error("native dash budget");
        put(payload,uint32_t(s.dash_len));for(int i=0;i<s.dash_len;++i)put(payload,double(s.dash_list[i]));
    }
    put(payload,uint64_t(path.bytes.size()));blob(payload,path.bytes.data(),path.bytes.size());event(out,r.kind,payload);
}
struct PixDrop {void operator()(fz_pixmap* p)const{mupdf::ll_fz_drop_pixmap(p);}};
struct DevDrop {void operator()(fz_device* d)const{mupdf::ll_fz_drop_device(d);}};
bool gradient(const fz_shade* s) {
    return s&&s->function&&s->function_stride>=mupdf::ll_fz_colorspace_n(s->colorspace)&&
        (s->type==FZ_LINEAR||(s->type==FZ_RADIAL&&std::abs(s->u.l_or_r.coords[0][2])<=1e-6f&&s->u.l_or_r.coords[1][2]>1e-6f));
}
// Request mode 2 captures actual mask coverage, including luminosity and transfer.
void raster(Job& job,Result& out,uint32_t start,uint32_t end,uint32_t mode,fz_rect area,double scale) {
    if(!(scale>0&&scale<=64)||!std::isfinite(scale))throw std::runtime_error("invalid raster scale");
    const double aw=std::max(0.,double(area.x1)-area.x0),ah=std::max(0.,double(area.y1)-area.y0);
    if(aw>0&&ah>0)scale=std::min({scale,8190./std::max(aw,ah),std::sqrt(8.*1024*1024/(aw*ah))*.98});
    const fz_matrix transform={float(scale),0,0,float(scale),0,0};
    fz_irect box=mupdf::ll_fz_round_rect(mupdf::ll_fz_transform_rect(area,transform));
    const int64_t w=int64_t(box.x1)-box.x0,h=int64_t(box.y1)-box.y0;
    if(w<=0||h<=0){if(mode==2||mode==3){mask_begin_event(out,area);mask_end_event(out);}return;}
    if(w>32768||h>32768||w*h>16*1024*1024)throw std::runtime_error("native raster budget");
    std::unique_ptr<fz_pixmap,PixDrop> pix(mupdf::ll_fz_new_pixmap_with_bbox(mupdf::ll_fz_device_rgb(),box,nullptr,1));
    mupdf::ll_fz_clear_pixmap(pix.get());
    if(mode==7)mupdf::ll_fz_clear_pixmap_with_value(pix.get(),255);
    std::unique_ptr<fz_device,DevDrop> dev(mupdf::ll_fz_new_draw_device(transform,pix.get()));
    // Restore paint state preceding the selected range without replaying its ink.
    const Record* defaults=nullptr;int flags=0;
    for(uint32_t i=0;i<(mode==7?0:start);++i) {const auto& r=*job.records[i];if(r.kind==20)defaults=&r;if(r.kind==19)flags=(flags|r.set)&~r.clear;}
    if(defaults)dispatch(*defaults,dev.get());mupdf::ll_fz_render_flags(dev.get(),flags,~flags);
    for(uint32_t i=mode==7?0:start;i<=end;++i)dispatch(*job.records[i],dev.get());
    if(mode==7){int clips=0;
        for(uint32_t i=0;i<=end;++i){const auto k=job.records[i]->kind;
            if(k==2||k==3||k==6||k==7||k==11||k==13)++clips;else if(k==12)--clips;}
        while(clips-->0)mupdf::ll_fz_pop_clip(dev.get());}
    if(mode==2||mode==3) {
        std::unique_ptr<fz_path,void(*)(const fz_path*)> white(mupdf::ll_fz_new_path(),mupdf::ll_fz_drop_path);
        mupdf::ll_fz_rectto(white.get(),area.x0,area.y0,area.x1,area.y1);const float c[]={1,1,1};
        mupdf::ll_fz_fill_path(dev.get(),white.get(),0,identity,mupdf::ll_fz_device_rgb(),c,1,default_params);
        mupdf::ll_fz_pop_clip(dev.get());
    }
    mupdf::ll_fz_close_device(dev.get());
    if(pix->n!=4||pix->stride<w*4)throw std::runtime_error("native raster layout");
    if(mode==2||mode==3)mask_begin_event(out,area);
    Result p;matrix(p,fz_matrix{float(w/scale),0,0,float(h/scale),float(box.x0/scale),float(box.y0/scale)});
    uint32_t preparation=0;const auto source_kind=job.records[start]->kind;
    // High image-flag bits describe actual preparation, not GPU drawing.
    if(source_kind==8)preparation|=0x100;       // CPU shading bitmap.
    if(source_kind==15)preparation|=0x200;     // CPU composite region.
    if(mode==7)preparation|=0x200;
    if(source_kind==17)preparation|=0x4000;    // CPU pattern bitmap.
    if(source_kind>=4&&source_kind<=7)preparation|=0x1000; // Glyph fallback.
    if(mode==2||mode==3||source_kind==13)preparation|=0x400; // Mask coverage.
    if(source_kind==13&&mode==1)preparation|=0x800; // Single image alpha.
    put(p,uint32_t(w));put(p,uint32_t(h));put(p,uint32_t(w*4));put(p,uint32_t(1)|preparation);
    for(int y=0;y<h;++y)blob(p,pix->samples+y*pix->stride,size_t(w)*4);
    event(out,mode==7?23u:9u,p);
    if(mode==2||mode==3)mask_end_event(out);
}
bool jpeg_rgb(fz_colorspace* cs) {
    auto* rgb=mupdf::ll_fz_device_rgb();if(cs==rgb)return true;
#if FZ_ENABLE_ICC
    // An explicit copy of the engine's sRGB profile is also an identity
    // conversion. Other RGB profiles must retain MuPDF color management.
    return cs&&cs->type==FZ_COLORSPACE_RGB&&(cs->flags&FZ_COLORSPACE_IS_ICC)&&
        (rgb->flags&FZ_COLORSPACE_IS_ICC)&&!std::memcmp(cs->u.icc.md5,rgb->u.icc.md5,16);
#else
    return false;
#endif
}
// Only unmodified, opaque RGB DCT images may bypass MuPDF decoding.
// PDF Decode arrays, masks, CMYK and non-sRGB profiles use the old path.
bool jpeg_image(Job& job,Result& out,const Record& r,uint32_t start,size_t fallback_bytes,double coverage,uint32_t target_w,uint32_t target_h) {
    const auto* im=r.image;
    if(r.kind!=9||r.alpha!=1||im->n!=3||im->bpc!=8||im->mask||im->imagemask||im->use_colorkey||im->use_decode||
        !jpeg_rgb(im->colorspace)||im->w<=0||im->h<=0||im->w>8192||im->h>8192||
        uint64_t(im->w)*im->h>16*1024*1024||coverage<.999999)return false;
    const uint64_t decoded=uint64_t(target_w)*target_h*4;
    if(decoded>64*1024*1024||decoded>fallback_bytes)return false;
    auto* compressed=mupdf::ll_fz_compressed_image_buffer(r.image);
    if(!compressed||compressed->params.type!=FZ_IMAGE_JPEG||compressed->params.u.jpeg.color_transform==0)return false;
    unsigned char* bytes=nullptr;const auto size=mupdf::ll_fz_buffer_storage(compressed->buffer,&bytes);
    // Keep the native JPEG path even when a tiny BGRA preview is smaller.
    // The original compressed source remains available for subsequent zooms.
    if(size<4||size>32*1024*1024||bytes[0]!=255||bytes[1]!=216)return false;
    // Reject RGB-coded JPEGs and malformed/mismatched headers before choosing
    // the WIC YCbCr path. WIC and PDF use the same encoded sampling grid.
    bool frame=false;
    for(size_t at=2;at+4<=size;){
        if(bytes[at++]!=255)return false;
        while(at<size&&bytes[at]==255)++at;if(at>=size)return false;
        const auto marker=bytes[at++];if(marker==0xda)break;
        if(marker==0xd9||marker==0||at+2>size)return false;
        const size_t length=size_t(bytes[at])*256+bytes[at+1];if(length<2||length>size-at)return false;
        if(marker==0xc0||marker==0xc2){
            if(length!=17||bytes[at+2]!=8||int(bytes[at+3])*256+bytes[at+4]!=im->h||
                int(bytes[at+5])*256+bytes[at+6]!=im->w||bytes[at+7]!=3||
                bytes[at+8]!=1||bytes[at+11]!=2||bytes[at+14]!=3)return false;
            frame=true;
        }else if(marker==0xee&&length>=14&&!std::memcmp(bytes+at+2,"Adobe",5)&&bytes[at+13]!=1)return false;
        at+=length;
    }
    if(!frame)return false;
    bool defaults_ok=true;
    for(uint32_t i=0;i<start;++i)if(job.records[i]->kind==20){
        auto* cs=mupdf::ll_fz_default_rgb(job.records[i]->defaults);defaults_ok=!cs||jpeg_rgb(cs);}
    if(!defaults_ok)return false;
    Result p;matrix(p,r.matrix);put(p,uint32_t(im->w));put(p,uint32_t(im->h));put(p,target_w);put(p,target_h);put(p,uint64_t(size));blob(p,bytes,size);
    event(out,24,p);return true;
}
// Images stay in their own sampling grid. Rasterizing a 2x2 source in page
// coordinates would add transparent borders and blur pixels when magnified.
void raster_image(Job& job,Result& out,uint32_t start,uint32_t end,fz_rect area,double density) {
    const Record* image=nullptr;
    for(uint32_t i=start;i<=end;++i)if(job.records[i]->kind==9||job.records[i]->kind==10){image=job.records[i].get();break;}
    if(!image)throw std::runtime_error("image request without image");
    const auto m=image->matrix;
    const auto inverse=mupdf::ll_fz_invert_matrix(m);
    const auto local=mupdf::ll_fz_transform_rect(area,inverse);
    const double span_x=std::clamp(double(local.x1),0.,1.)-std::clamp(double(local.x0),0.,1.);
    const double span_y=std::clamp(double(local.y1),0.,1.)-std::clamp(double(local.y0),0.,1.);
    // Cap the uploaded crop, not the original image. High-zoom visible crops
    // retain their source pixels even for very long or skewed PDF images.
    double tw=std::max(1.,std::min({double(image->image->w),std::ceil(std::hypot(m.a,m.b)*density),8190./std::max(span_x,1e-12)}));
    double th=std::max(1.,std::min({double(image->image->h),std::ceil(std::hypot(m.c,m.d)*density),8190./std::max(span_y,1e-12)}));
    const double desired=(std::max(0.,span_x)*tw+2)*(std::max(0.,span_y)*th+2);
    if(desired>8.*1024*1024){const double factor=std::sqrt(8.*1024*1024/desired)*.98;
        tw=std::max(1.,tw*factor);th=std::max(1.,th*factor);}
    const int x0=int(std::floor(std::clamp(double(local.x0),0.,1.)*tw));
    const int y0=int(std::floor(std::clamp(double(local.y0),0.,1.)*th));
    const int x1=int(std::ceil(std::clamp(double(local.x1),0.,1.)*tw));
    const int y1=int(std::ceil(std::clamp(double(local.y1),0.,1.)*th));
    const int w=x1-x0,h=y1-y0;if(w<=0||h<=0)return;
    if(w>32768||h>32768||int64_t(w)*h>16*1024*1024)throw std::runtime_error("native image budget");
    if(start==end){
        const bool complete=area.x0<=image->area.x0&&area.y0<=image->area.y0&&area.x1>=image->area.x1&&area.y1>=image->area.y1;
        if(complete&&jpeg_image(job,out,*image,start,size_t(w)*h*4,std::max(0.,span_x)*std::max(0.,span_y),uint32_t(std::ceil(tw)),uint32_t(std::ceil(th))))return;
    }
    const fz_matrix scale={float(tw),0,0,float(th),0,0};
    std::unique_ptr<fz_pixmap,PixDrop> pix(mupdf::ll_fz_new_pixmap_with_bbox(mupdf::ll_fz_device_rgb(),fz_irect{x0,y0,x1,y1},nullptr,1));
    mupdf::ll_fz_clear_pixmap(pix.get());
    std::unique_ptr<fz_device,DevDrop> dev(mupdf::ll_fz_new_draw_device(mupdf::ll_fz_concat(inverse,scale),pix.get()));
    const Record* defaults=nullptr;int flags=0;
    for(uint32_t i=0;i<start;++i){const auto& r=*job.records[i];if(r.kind==20)defaults=&r;if(r.kind==19)flags=(flags|r.set)&~r.clear;}
    if(defaults)dispatch(*defaults,dev.get());mupdf::ll_fz_render_flags(dev.get(),flags,~flags);
    for(uint32_t i=start;i<=end;++i)dispatch(*job.records[i],dev.get());
    mupdf::ll_fz_close_device(dev.get());
    if(pix->n!=4)throw std::runtime_error("native image layout");
    const fz_matrix crop={float(w/tw),0,0,float(h/th),float(x0/tw),float(y0/th)};
    Result p;matrix(p,mupdf::ll_fz_concat(crop,m));put(p,uint32_t(w));put(p,uint32_t(h));put(p,uint32_t(w*4));
    uint32_t preparation=image->kind==10?0x2000u:0u;
    if(end>start)preparation|=0xc00; // Image alpha fusion and mask coverage.
    put(p,uint32_t(image->image->interpolate)|(image->kind==9&&image->image->bpc>1?2u:0u)|preparation);
    for(int y=0;y<h;++y)blob(p,pix->samples+y*pix->stride,size_t(w)*4);event(out,9,p);
}
GlyphOutline type3_outline(Job& job,fz_font* font,int gid);
struct ShadeMesh {const Record* record;Job* job;Result vertices;bool failed=false;};
static void mesh_prepare(fz_context*,void* opaque,fz_vertex* vertex,const float* colors) noexcept {
    auto& state=*static_cast<ShadeMesh*>(opaque);
    try {const auto& r=*state.record;const auto& shade=*r.shade;const float* source=colors;
        if(shade.function_stride&&shade.function){float t=colors[0];
            if(shade.type>=4&&shade.type<=7){const float span=shade.u.m.c1[0]-shade.u.m.c0[0];if(span!=0)t=(t-shade.u.m.c0[0])/span;}
            vertex->c[4]=std::clamp(t,0.f,1.f);const int i=std::clamp(int(t*255+.5f),0,255);source=shade.function+i*shade.function_stride;}
        float rgb[3]={};mupdf::ll_fz_convert_color(shade.colorspace,source,mupdf::ll_fz_device_rgb(),rgb,nullptr,r.params);
        for(int i=0;i<3;++i)vertex->c[i]=std::clamp(rgb[i],0.f,1.f);vertex->c[3]=r.alpha;
    }catch(...){state.failed=true;}
}
static void mesh_triangle(fz_context*,void* opaque,fz_vertex* a,fz_vertex* b,fz_vertex* c) noexcept {
    auto& state=*static_cast<ShadeMesh*>(opaque);if(state.failed)return;
    try {if(state.vertices.count>=65536||std::chrono::steady_clock::now()>=state.job->deadline)throw std::runtime_error("mesh budget");
        for(const auto* v:{a,b,c}){put(state.vertices,v->p.x);put(state.vertices,v->p.y);for(int i=0;i<4;++i)put(state.vertices,v->c[i]);}
        ++state.vertices.count;
    }catch(...){state.failed=true;}
}
fz_vertex mesh_midpoint(ShadeMesh& state,const fz_vertex& a,const fz_vertex& b) {
    fz_vertex v{};v.p={.5f*(a.p.x+b.p.x),.5f*(a.p.y+b.p.y)};v.c[4]=.5f*(a.c[4]+b.c[4]);
    const auto& r=*state.record;const int index=std::clamp(int(v.c[4]*255+.5f),0,255);
    mupdf::ll_fz_convert_color(r.shade->colorspace,r.shade->function+index*r.shade->function_stride,
        mupdf::ll_fz_device_rgb(),v.c,nullptr,r.params);
    for(int i=0;i<3;++i)v.c[i]=std::clamp(v.c[i],0.f,1.f);v.c[3]=r.alpha;return v;
}
void mesh_subdivide(ShadeMesh& state,fz_vertex& a,fz_vertex& b,fz_vertex& c,int depth) {
    if(state.failed)return;
    auto ab=mesh_midpoint(state,a,b),bc=mesh_midpoint(state,b,c),ca=mesh_midpoint(state,c,a);
    const auto nonlinear=[](const fz_vertex& x,const fz_vertex& y,const fz_vertex& mid){
        for(int i=0;i<3;++i)if(std::abs(mid.c[i]-.5f*(x.c[i]+y.c[i]))>2.f/255)return true;return false;};
    const float range=std::max({a.c[4],b.c[4],c.c[4]})-std::min({a.c[4],b.c[4],c.c[4]});
    if(depth<7&&((depth<2&&range>1.f/64)||nonlinear(a,b,ab)||nonlinear(b,c,bc)||nonlinear(c,a,ca))){
        mesh_subdivide(state,a,ab,ca,depth+1);mesh_subdivide(state,ab,b,bc,depth+1);
        mesh_subdivide(state,ca,bc,c,depth+1);mesh_subdivide(state,ab,bc,ca,depth+1);
    }else mesh_triangle(nullptr,&state,&a,&b,&c);
}
static void mesh_adaptive_triangle(fz_context*,void* opaque,fz_vertex* a,fz_vertex* b,fz_vertex* c) noexcept {
    auto& state=*static_cast<ShadeMesh*>(opaque);if(state.failed)return;
    try{if(state.record->shade->function_stride)mesh_subdivide(state,*a,*b,*c,0);
        else mesh_triangle(nullptr,opaque,a,b,c);}catch(...){state.failed=true;}
}
void materialize(Job& job,Result& out,const Record& r,fz_rect area,double scale) {
    if(r.kind==8&&!gradient(r.shade)) {
        // Function shadings may arrive as an unnecessarily dense sampling grid.
        // Resample its native values, retaining a bounded vector mesh.
        fz_shade sampled=*r.shade;std::vector<float> values;
        if(sampled.type==FZ_FUNCTION_BASED&&(sampled.u.f.xdivs>64||sampled.u.f.ydivs>64)) {
            const auto source=sampled.u.f;const int nx=std::min(source.xdivs,64),ny=std::min(source.ydivs,64);
            const int channels=mupdf::ll_fz_colorspace_n(sampled.colorspace);values.reserve(size_t(nx+1)*(ny+1)*channels);
            for(int y=0;y<=ny;++y)for(int x=0;x<=nx;++x){
                const double sx=double(x)*source.xdivs/nx,sy=double(y)*source.ydivs/ny;
                const int x0=int(sx),y0=int(sy),x1=std::min(x0+1,source.xdivs),y1=std::min(y0+1,source.ydivs);
                const float fx=float(sx-x0),fy=float(sy-y0);
                for(int c=0;c<channels;++c){const auto at=[&](int px,int py){return source.fn_vals[(size_t(py)*(source.xdivs+1)+px)*channels+c];};
                    values.push_back((1-fy)*((1-fx)*at(x0,y0)+fx*at(x1,y0))+fy*((1-fx)*at(x0,y1)+fx*at(x1,y1)));}}
            sampled.u.f.xdivs=nx;sampled.u.f.ydivs=ny;sampled.u.f.fn_vals=values.data();
        }
        ShadeMesh mesh{&r,&job,{},false};mupdf::ll_fz_process_shade(&sampled,mupdf::ll_fz_concat(sampled.matrix,r.matrix),area,mesh_prepare,mesh_adaptive_triangle,&mesh);
        if(mesh.failed){if(std::chrono::steady_clock::now()>=job.deadline)throw std::runtime_error("GPU scene time budget exceeded");
            throw std::runtime_error("native mesh budget exceeded");}
        if(!mesh.vertices.bytes.empty()){Result p;put(p,uint64_t(mesh.vertices.bytes.size()));blob(p,mesh.vertices.bytes.data(),mesh.vertices.bytes.size());event(out,21,p);}return;
    }
    if(r.kind==13){float rgb[3]={};if(r.cs)mupdf::ll_fz_convert_color(r.cs,r.color,mupdf::ll_fz_device_rgb(),rgb,nullptr,r.params);
        uint32_t bg=0;if(r.flags){bg=0xff000000;for(int i=0;i<3;++i)bg|=uint32_t(std::clamp(int(rgb[i]*255+.5f),0,255))<<(16-8*i);}
        mask_begin_event(out,area,r.flags!=0,bg);return;}
    if(r.kind==14){mask_end_event(out,r.function);return;}
    if(r.kind==11){mask_begin_event(out,area);Job mask;
        auto paint=std::make_unique<Record>();paint->kind=10;paint->image=mupdf::ll_fz_keep_image(r.image);paint->matrix=r.matrix;
        paint->cs=mupdf::ll_fz_keep_colorspace(mupdf::ll_fz_device_rgb());paint->color[0]=paint->color[1]=paint->color[2]=1;paint->params=r.params;
        mask.records.push_back(std::move(paint));raster_image(mask,out,0,0,area,scale);mask_end_event(out);return;}
    if(r.kind==8&&gradient(r.shade)) {
        const auto& s=*r.shade;Result p;put(p,uint32_t(s.type));matrix(p,mupdf::ll_fz_concat(s.matrix,r.matrix));rect(p,area);
        for(const auto& circle:s.u.l_or_r.coords)for(float x:circle)put(p,double(x));
        put(p,uint32_t(s.u.l_or_r.extend[0]));put(p,uint32_t(s.u.l_or_r.extend[1]));
        for(int i=0;i<256;++i) {
            float rgb[3]={};mupdf::ll_fz_convert_color(s.colorspace,s.function+i*s.function_stride,mupdf::ll_fz_device_rgb(),rgb,nullptr,r.params);
            for(float x:rgb)put(p,double(x));put(p,double(r.alpha));
        }
        event(out,8,p);return;
    }
    if(r.kind<=3){path_event(out,r,path_bytes(r.path),r.matrix);return;}
    if(r.kind>=4&&r.kind<=7) {
        if(r.raster_text)throw std::runtime_error("font has no vector outline");
        // Clip outlines are merged in page space; fills retain reusable glyph space.
        struct Glyph {const GlyphOutline* outline;fz_matrix m;};std::vector<Glyph> glyphs;
        for(auto* s=r.text->head;s;s=s->next)for(int i=0;i<s->len;++i) {
            auto item=s->items[i];if(item.gid==-1)continue;
            int gid=item.gid<0?mupdf::ll_fz_encode_character(s->font,item.ucs):item.gid;
            // Type3 stroke/clip text has different coverage semantics. Keep its
            // existing capture path, including when a filled glyph is cached.
            if(s->font->t3procs&&r.kind!=4)throw std::runtime_error("font has no vector outline");
            auto key=std::make_pair(s->font,gid);auto found=job.glyphs.find(key);
            if(found==job.glyphs.end()) {
                std::unique_ptr<fz_path,void(*)(const fz_path*)> p(mupdf::ll_fz_outline_glyph(s->font,gid,identity),mupdf::ll_fz_drop_path);
                GlyphOutline outline;
                if(p)outline.path=path_bytes(p.get());
                else outline=type3_outline(job,s->font,gid);
                job.glyph_bytes+=outline.path.bytes.size();
                if(job.glyph_bytes>256*1024*1024)throw std::runtime_error("native glyph budget exceeded");
                found=job.glyphs.emplace(key,std::move(outline)).first;
            }
            auto m=s->trm;m.e=item.x;m.f=item.y;glyphs.push_back({&found->second,r.kind==4?mupdf::ll_fz_concat(m,r.matrix):m});
        }
        if(r.kind==4)for(const auto& glyph:glyphs) {
            // A borrowed temporary record must not drop the original resources.
            Record paint;paint.kind=0;paint.flags=uint32_t(glyph.outline->even_odd);
            paint.alpha=r.alpha;paint.params=r.params;paint.cs=mupdf::ll_fz_keep_colorspace(r.cs);
            std::copy(r.color,r.color+FZ_MAX_COLORS,paint.color);path_event(out,paint,glyph.outline->path,glyph.m,true);
        } else {
            Result merged;
            for(const auto& glyph:glyphs) {
                const auto& b=glyph.outline->path.bytes;size_t at=0;
                while(at<b.size()) {auto tag=b[at++];merged.bytes.push_back(tag);const int n=tag==3?6:tag==4?0:2;
                    for(int j=0;j<n;j+=2){double x,y;std::memcpy(&x,b.data()+at,8);std::memcpy(&y,b.data()+at+8,8);at+=16;
                        const auto& m=glyph.m;put(merged,double(x*m.a+y*m.c+m.e));put(merged,double(x*m.b+y*m.d+m.f));}
                }
            }
            Record paint;paint.kind=r.kind==5?1u:r.kind==7?3u:2u;
            paint.stroke=mupdf::ll_fz_keep_stroke_state(r.stroke);paint.cs=mupdf::ll_fz_keep_colorspace(r.cs);
            paint.alpha=r.alpha;paint.params=r.params;std::copy(r.color,r.color+FZ_MAX_COLORS,paint.color);
            path_event(out,paint,merged,r.matrix);
        }
        return;
    }
    Result p;
    if(r.kind==15){put(p,double(r.alpha));put(p,uint32_t(r.blend)|((r.cs&&mupdf::ll_fz_colorspace_n(r.cs)==4)?256u:0u));put(p,uint32_t(r.isolated));put(p,uint32_t(r.knockout));}
    if(r.kind==12||r.kind==15||r.kind==16)event(out,r.kind,p);
    else if(r.kind!=19&&r.kind!=20)throw std::runtime_error("unplanned native primitive");
}
template<class T> T read(const unsigned char*& p,const unsigned char* end) {
    if(size_t(end-p)<sizeof(T))throw std::runtime_error("truncated native request");T v;std::memcpy(&v,p,sizeof(T));p+=sizeof(T);return v;
}
} // namespace

static fz_device* leaflet_scene_device(leaflet_scene::Job& job) {
    using namespace leaflet_scene;
    auto* dev=reinterpret_cast<Device*>(mupdf::ll_fz_new_device_of_size(int(sizeof(Device))));dev->job=&job;
    dev->super.fill_path=fill_path;dev->super.stroke_path=stroke_path;dev->super.clip_path=clip_path;dev->super.clip_stroke_path=clip_stroke_path;
    dev->super.fill_text=fill_text;dev->super.stroke_text=stroke_text;dev->super.clip_text=clip_text;dev->super.clip_stroke_text=clip_stroke_text;
    dev->super.fill_shade=fill_shade;dev->super.fill_image=fill_image;dev->super.fill_image_mask=fill_image_mask;dev->super.clip_image_mask=clip_image_mask;
    dev->super.pop_clip=pop_clip;dev->super.begin_mask=begin_mask;dev->super.end_mask=end_mask;dev->super.begin_group=begin_group;dev->super.end_group=end_group;
    dev->super.begin_tile=begin_tile;dev->super.end_tile=end_tile;dev->super.render_flags=render_flags;dev->super.set_default_colorspaces=set_defaults;
    return &dev->super;
}

namespace leaflet_scene {
std::unique_ptr<Record> placed_record(const Record& source,fz_matrix transform) {
    auto r=std::make_unique<Record>();r->kind=source.kind;r->flags=source.flags;
    r->path=mupdf::ll_fz_keep_path(source.path);r->text=mupdf::ll_fz_keep_text(source.text);
    r->stroke=mupdf::ll_fz_keep_stroke_state(source.stroke);r->image=mupdf::ll_fz_keep_image(source.image);
    r->shade=mupdf::ll_fz_keep_shade(source.shade);r->cs=mupdf::ll_fz_keep_colorspace(source.cs);
    r->defaults=mupdf::ll_fz_keep_default_colorspaces(source.defaults);r->function=mupdf::ll_fz_keep_function(source.function);
    r->matrix=mupdf::ll_fz_concat(source.matrix,transform);r->area=mupdf::ll_fz_transform_rect(source.area,transform);
    r->scissor=source.kind==17?source.scissor:mupdf::ll_fz_transform_rect(source.scissor,transform);r->view=source.view;
    r->params=source.params;std::copy(source.color,source.color+FZ_MAX_COLORS,r->color);
    r->alpha=source.alpha;r->xstep=source.xstep;r->ystep=source.ystep;r->isolated=source.isolated;
    r->knockout=source.knockout;r->blend=source.blend;r->id=source.id;r->doc_id=source.doc_id;r->set=source.set;r->clear=source.clear;r->raster_text=source.raster_text;
    return r;
}
void normalize_records(Job& job,int depth=0) {
    if(depth>8)throw std::runtime_error("nested glyph/pattern budget exceeded");
    std::vector<std::unique_ptr<Record>> expanded;expanded.reserve(job.records.size());
    const auto expansion_limit=std::max<size_t>(100000,job.records.size());
    const auto append=[&](std::unique_ptr<Record> record){
        if(std::chrono::steady_clock::now()>=job.deadline)throw std::runtime_error("GPU scene time budget exceeded");
        if(expanded.size()>=expansion_limit)throw std::runtime_error("native expansion budget exceeded");
        expanded.push_back(std::move(record));};
    for(size_t index=0;index<job.records.size();++index) {
        auto& record=*job.records[index];
        if(record.kind==4) {
            bool type3=false;for(auto* s=record.text->head;s;s=s->next)if(s->font->t3procs)type3=true;
            if(type3) {
                bool complex=false;
                for(auto* s=record.text->head;s&&!complex;s=s->next)if(s->font->t3procs)for(int i=0;i<s->len;++i){
                    const int gid=s->items[i].gid;if(gid==-1)continue;const auto key=std::make_pair(s->font,gid);
                    if(job.glyphs.find(key)!=job.glyphs.end())continue;
                    try{auto outline=type3_outline(job,s->font,gid);job.glyph_bytes+=outline.path.bytes.size();
                        if(job.glyph_bytes>256*1024*1024)throw std::runtime_error("native glyph budget exceeded");
                        job.glyphs.emplace(key,std::move(outline));}
                    catch(const std::runtime_error& e){if(std::strcmp(e.what(),"font has no vector outline"))throw;complex=true;break;}}
                // Keep the compact outline/instancing path for ordinary Type3
                // fonts; expand programs only when they need more operations.
                if(!complex){append(std::move(job.records[index]));continue;}
                for(auto* s=record.text->head;s;s=s->next)for(int i=0;i<s->len;++i) {
                    const auto& item=s->items[i];if(item.gid==-1)continue;
                    auto local=s->trm;local.e=item.x;local.f=item.y;
                    const auto position=mupdf::ll_fz_concat(local,record.matrix);
                    const auto append_text=[&](bool raster){
                        auto glyph=std::make_unique<Record>();glyph->kind=4;glyph->text=mupdf::ll_fz_new_text();
                        mupdf::ll_fz_show_glyph(glyph->text,s->font,local,item.gid,item.ucs,s->wmode,0,FZ_BIDI_NEUTRAL,FZ_LANG_UNSET);
                        glyph->matrix=record.matrix;color(*glyph,record.cs,record.color,record.alpha,record.params);
                        glyph->raster_text=raster;glyph->area=mupdf::ll_fz_bound_text(glyph->text,nullptr,glyph->matrix);append(std::move(glyph));};
                    if(s->font->t3procs&&item.gid>=0&&item.gid<256) {
                        mupdf::ll_fz_prepare_t3_glyph(s->font,item.gid);
                        Job glyph;glyph.deadline=job.deadline;glyph.record_limit=4096;
                        std::unique_ptr<fz_device,DevDrop> device(leaflet_scene_device(glyph));
                        mupdf::ll_fz_run_t3_glyph(s->font,item.gid,identity,device.get());mupdf::ll_fz_close_device(device.get());
                        if(glyph.failed){
                            if(std::chrono::steady_clock::now()>=job.deadline)throw std::runtime_error("GPU scene time budget exceeded");
                            append_text(true);continue;}
                        try{normalize_records(glyph,depth+1);}
                        catch(const std::runtime_error& e){
                            if(std::strcmp(e.what(),"nested glyph/pattern budget exceeded")&&
                               std::strcmp(e.what(),"native expansion budget exceeded"))throw;
                            append_text(true);continue;}
                        const bool uncolored=(s->font->t3flags[item.gid]&FZ_DEVFLAG_COLOR)==0;
                        if(record.alpha<1.f&&!glyph.records.empty()) {auto group=std::make_unique<Record>();group->kind=15;group->alpha=record.alpha;
                            group->area=mupdf::ll_fz_bound_text(record.text,nullptr,record.matrix);append(std::move(group));}
                        for(const auto& child:glyph.records) {
                            auto placed=placed_record(*child,position);
                            if(uncolored&&(placed->kind==0||placed->kind==1||placed->kind==4||placed->kind==5||placed->kind==10)) {
                                mupdf::ll_fz_drop_colorspace(placed->cs);placed->cs=mupdf::ll_fz_keep_colorspace(record.cs);
                                std::copy(record.color,record.color+FZ_MAX_COLORS,placed->color);placed->params=record.params;}
                            append(std::move(placed));
                        }
                        if(record.alpha<1.f&&!glyph.records.empty()){auto group=std::make_unique<Record>();group->kind=16;append(std::move(group));}
                    } else append_text(false);
                }
                continue;
            }
        }
        if(record.kind==17) {
            size_t end=index+1;int nesting=1;
            for(;end<job.records.size();++end){if(job.records[end]->kind==17)++nesting;else if(job.records[end]->kind==18&&--nesting==0)break;}
            if(end==job.records.size())throw std::runtime_error("unclosed native tile");
            if(depth>=8){
                // Keep the complete tile program for the bounded raster planner
                // instead of rejecting the whole page on deep vector expansion.
                for(size_t child=index;child<=end;++child)append(std::move(job.records[child]));
                index=end;continue;
            }
            const double xs=std::abs(record.xstep),ys=std::abs(record.ystep);
            if(xs>1e-6&&ys>1e-6) {
                const auto& a=record.scissor;const auto& v=record.view;
                const auto ix0=std::floor((a.x0-v.x1)/xs)+1,ix1=std::ceil((a.x1-v.x0)/xs);
                const auto iy0=std::floor((a.y0-v.y1)/ys)+1,iy1=std::ceil((a.y1-v.y0)/ys);
                const double cells=std::max(0.,ix1-ix0)*std::max(0.,iy1-iy0);
                if(cells<=4096&&cells*double(end-index+2)+double(expanded.size())<100000) {
                    const auto clip=[&](fz_rect bounds,fz_matrix matrix){auto r=std::make_unique<Record>();r->kind=2;r->matrix=matrix;r->area=mupdf::ll_fz_transform_rect(bounds,matrix);
                        r->path=mupdf::ll_fz_new_path();mupdf::ll_fz_rectto(r->path,bounds.x0,bounds.y0,bounds.x1,bounds.y1);append(std::move(r));};
                    const auto pop=[&](){auto r=std::make_unique<Record>();r->kind=12;append(std::move(r));};
                    clip(a,record.matrix);
                    for(double y=iy0;y<iy1;++y)for(double x=ix0;x<ix1;++x) {
                        const float dx=float(x*xs),dy=float(y*ys);const fz_matrix shift={1,0,0,1,dx*record.matrix.a+dy*record.matrix.c,dx*record.matrix.b+dy*record.matrix.d};
                        Job tile;tile.deadline=job.deadline;
                        for(size_t child=index+1;child<end;++child)tile.records.push_back(placed_record(*job.records[child],shift));
                        normalize_records(tile,depth+1);clip(v,mupdf::ll_fz_concat(record.matrix,shift));
                        for(auto& child:tile.records)append(std::move(child));pop();
                    }
                    pop();index=end;continue;
                }
            }
        }
        append(std::move(job.records[index]));
    }
    job.records=std::move(expanded);
}
GlyphOutline type3_outline(Job& job,fz_font* font,int gid) {
    if(!font->t3procs||gid<0||gid>=256)throw std::runtime_error("font has no vector outline");
    mupdf::ll_fz_prepare_t3_glyph(font,gid);
    const auto flags=font->t3flags[gid];
    // A masked glyph inherits the enclosing text color. Colored glyphs and
    // graphics-state-dependent programs must retain MuPDF's raster handling.
    if(!(flags&FZ_DEVFLAG_MASK)||(flags&(FZ_DEVFLAG_COLOR|FZ_DEVFLAG_UNCACHEABLE)))
        throw std::runtime_error("font has no vector outline");
    Job captured;captured.deadline=job.deadline;captured.record_limit=32;
    std::unique_ptr<fz_device,DevDrop> device(leaflet_scene_device(captured));
    mupdf::ll_fz_run_t3_glyph(font,gid,identity,device.get());
    mupdf::ll_fz_close_device(device.get());
    if(captured.failed) {
        if(error=="GPU scene time budget exceeded")throw std::runtime_error(error);
        throw std::runtime_error("font has no vector outline");
    }
    const Record* fill=nullptr;
    for(const auto& record:captured.records) {
        if(record->kind==19||record->kind==20)continue;
        // One complete fill preserves its holes and winding rule. Do not merge
        // independently painted paths: overlaps and opacity could change.
        if(record->kind!=0||record->alpha!=1.f||fill)
            throw std::runtime_error("font has no vector outline");
        fill=record.get();
    }
    GlyphOutline result;
    if(fill) {
        // Walk packed display-list paths directly; never mutate/clone their
        // internal storage. Apply the Type3 font matrix to our owned bytes.
        result.path=path_bytes(fill->path);result.even_odd=fill->flags!=0;
        auto& bytes=result.path.bytes;size_t at=0;
        while(at<bytes.size()) {
            const auto tag=bytes[at++];const int n=tag==3?6:tag==4?0:2;
            for(int j=0;j<n;j+=2) {
                double x,y;std::memcpy(&x,bytes.data()+at,8);std::memcpy(&y,bytes.data()+at+8,8);
                const auto& m=fill->matrix;const double tx=x*m.a+y*m.c+m.e,ty=x*m.b+y*m.d+m.f;
                std::memcpy(bytes.data()+at,&tx,8);std::memcpy(bytes.data()+at+8,&ty,8);at+=16;
            }
        }
    }
    return result;
}
} // namespace leaflet_scene

extern "C" __declspec(dllexport) int leaflet_scene_probe(fz_page* page,uint64_t* score,uint64_t* operations) noexcept {
    using namespace leaflet_scene;
    try {if(!page||!score||!operations)return 0;Job job;job.count_only=true;
        std::unique_ptr<fz_device,DevDrop> dev(leaflet_scene_device(job));
        mupdf::ll_fz_run_page(page,dev.get(),identity,&job.cookie);mupdf::ll_fz_close_device(dev.get());
        *score=job.score;*operations=job.operations;return 1;
    }catch(...){return 0;}
}

extern "C" __declspec(dllexport) void leaflet_scene_drop(leaflet_scene::Job* job) noexcept {delete job;}
extern "C" __declspec(dllexport) uint32_t leaflet_scene_abi() noexcept{return 4;}
extern "C" __declspec(dllexport) leaflet_scene::Job* leaflet_scene_collect(fz_page* page,double timeout,const unsigned char** data,size_t* size) noexcept {
    using namespace leaflet_scene;
    try {
        if(!page||!data||!size)return nullptr;
        auto job=std::make_unique<Job>();job->page=mupdf::ll_fz_bound_page(page);
        if(!std::isfinite(timeout))return nullptr;
        if(timeout>=0)job->deadline=std::chrono::steady_clock::now()+std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(std::min(timeout,3600.)));
        std::unique_ptr<fz_device,DevDrop> device(leaflet_scene_device(*job));
        // Direct page execution: retained resources survive until this job is dropped.
        mupdf::ll_fz_run_page(page,device.get(),identity,&job->cookie);mupdf::ll_fz_close_device(device.get());
        if(job->failed)return nullptr;
        normalize_records(*job);
        for(const auto& r:job->records){put(job->metadata,r->kind);
            const uint32_t flags=r->raster_text?0x80000000u:r->image?(uint32_t(std::min(r->image->w,65535))|(uint32_t(std::min(r->image->h,65535))<<16)):
                r->shade?(gradient(r->shade)?uint32_t(r->shade->type):4u):r->flags;
            put(job->metadata,flags);rect(job->metadata,r->area);put(job->metadata,double(r->alpha));}
        *data=job->metadata.bytes.data();*size=job->metadata.bytes.size();return job.release();
    }catch(const std::exception& e){error=e.what();return nullptr;}catch(...){error="native collection failure";return nullptr;}
}
extern "C" __declspec(dllexport) Result* leaflet_scene_materialize(leaflet_scene::Job* job,const unsigned char* requests,size_t length,const unsigned char** data,size_t* size) noexcept {
    using namespace leaflet_scene;
    try {
        if(!job||!requests||!data||!size||length%56||length>budget)return nullptr;
        auto out=std::make_unique<Result>();const auto* p=requests;const auto* end=p+length;
        while(p<end) {
            if(std::chrono::steady_clock::now()>=job->deadline)throw std::runtime_error("GPU scene time budget exceeded");
            const auto mode=read<uint32_t>(p,end),start=read<uint32_t>(p,end),last=read<uint32_t>(p,end);(void)read<uint32_t>(p,end);
            const double x0=read<double>(p,end),y0=read<double>(p,end),x1=read<double>(p,end),y1=read<double>(p,end),scale=read<double>(p,end);
            if(start>last||last>=job->records.size()||mode>7||mode==4)throw std::runtime_error("invalid native request");
            if(mode==5||mode==6)raster_image(*job,*out,start,last,fz_rect{float(x0),float(y0),float(x1),float(y1)},scale);
            else if(mode)raster(*job,*out,start,last,mode,fz_rect{float(x0),float(y0),float(x1),float(y1)},scale);
            else {
                const auto& r=*job->records[start];
                try {materialize(*job,*out,r,fz_rect{float(x0),float(y0),float(x1),float(y1)},scale);}
                catch(const std::runtime_error& e) {
                    if(r.kind==8&&!std::strcmp(e.what(),"native mesh budget exceeded")) {
                        const double pixels=std::max(1.,(x1-x0)*(y1-y0));
                        raster(*job,*out,start,start,1,fz_rect{float(x0),float(y0),float(x1),float(y1)},std::min(scale,std::sqrt(4*1024*1024/pixels)*.98));continue;}
                    if((r.kind<4||r.kind>7)||std::strcmp(e.what(),"font has no vector outline"))throw;
                    raster(*job,*out,start,start,r.kind>=6?3u:1u,fz_rect{float(x0),float(y0),float(x1),float(y1)},scale);
                }
            }
        }
        *data=out->bytes.data();*size=out->bytes.size();return out.release();
    }catch(const std::exception& e){error=e.what();return nullptr;}catch(...){error="native materialization failure";return nullptr;}
}
extern "C" __declspec(dllexport) const char* leaflet_scene_error() noexcept{return leaflet_scene::error.c_str();}

// Standalone reader worker input. All SDK ownership remains on this thread.
extern "C" __declspec(dllexport) leaflet_scene::Job* leaflet_scene_open(const char* filename,int page_index,double timeout,
    double* bounds,const unsigned char** data,size_t* size) noexcept {
    using namespace leaflet_scene;
    fz_document* doc=nullptr;fz_page* page=nullptr;
    try {
        const auto started=std::chrono::steady_clock::now();
        if(!filename||!bounds||page_index<0)return nullptr;
        mupdf::ll_fz_register_document_handlers();mupdf::ll_fz_set_aa_level(8);
        doc=mupdf::ll_fz_open_document(filename);
        if(mupdf::ll_fz_needs_password(doc))throw std::runtime_error("password required for worker input");
        page=mupdf::ll_fz_load_page(doc,page_index);
        const auto r=mupdf::ll_fz_bound_page(page);
        const double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
        auto* job=leaflet_scene_collect(page,timeout<0?timeout:std::max(0.,timeout-elapsed),data,size);
        if(!job){mupdf::ll_fz_drop_page(page);mupdf::ll_fz_drop_document(doc);return nullptr;}
        job->owned_page=page;job->owned_document=doc;
        bounds[0]=r.x0;bounds[1]=r.y0;bounds[2]=r.x1;bounds[3]=r.y1;
        return job;
    }catch(const std::exception& e){error=e.what();}catch(...){error="native PDF open failure";}
    mupdf::ll_fz_drop_page(page);mupdf::ll_fz_drop_document(doc);return nullptr;
}
