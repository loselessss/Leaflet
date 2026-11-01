// MuPDF SDK adapter only. Scope selection and GPU compilation live in Rust.
#include <algorithm>
#include <cmath>
#include <memory>
#include <stdexcept>
#include <map>
#include <chrono>

namespace leaflet_scene {
thread_local std::string error;
constexpr size_t budget=256u*1024*1024;
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
    ~Record() {
        mupdf::ll_fz_drop_path(path);mupdf::ll_fz_drop_text(text);
        mupdf::ll_fz_drop_stroke_state(stroke);mupdf::ll_fz_drop_image(image);
        mupdf::ll_fz_drop_shade(shade);mupdf::ll_fz_drop_colorspace(cs);
        mupdf::ll_fz_drop_default_colorspaces(defaults);mupdf::ll_fz_drop_function(function);
    }
};
struct Job {std::vector<std::unique_ptr<Record>> records;Result metadata;bool failed=false;fz_rect page;
    fz_document* owned_document=nullptr;fz_page* owned_page=nullptr;
    std::map<std::pair<fz_font*,int>,Result> glyphs;size_t glyph_bytes=0;
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
        if(job.records.size()>=1048576||job.records.size()>128*1024*1024/sizeof(Record))throw std::runtime_error("native command budget exceeded");
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
    const fz_matrix transform={float(scale),0,0,float(scale),0,0};
    fz_irect box=mupdf::ll_fz_round_rect(mupdf::ll_fz_transform_rect(area,transform));
    const int64_t w=int64_t(box.x1)-box.x0,h=int64_t(box.y1)-box.y0;
    if(w<=0||h<=0){if(mode==2||mode==3){Result p;rect(p,area);event(out,13,p);event(out,14,Result{});}return;}
    if(w>32768||h>32768||w*h>16*1024*1024)throw std::runtime_error("native raster budget");
    std::unique_ptr<fz_pixmap,PixDrop> pix(mupdf::ll_fz_new_pixmap_with_bbox(mupdf::ll_fz_device_rgb(),box,nullptr,1));
    mupdf::ll_fz_clear_pixmap(pix.get());
    std::unique_ptr<fz_device,DevDrop> dev(mupdf::ll_fz_new_draw_device(transform,pix.get()));
    // Restore paint state preceding the selected range without replaying its ink.
    const Record* defaults=nullptr;int flags=0;
    for(uint32_t i=0;i<start;++i) {const auto& r=*job.records[i];if(r.kind==20)defaults=&r;if(r.kind==19)flags=(flags|r.set)&~r.clear;}
    if(defaults)dispatch(*defaults,dev.get());mupdf::ll_fz_render_flags(dev.get(),flags,~flags);
    for(uint32_t i=start;i<=end;++i)dispatch(*job.records[i],dev.get());
    if(mode==2||mode==3) {
        std::unique_ptr<fz_path,void(*)(const fz_path*)> white(mupdf::ll_fz_new_path(),mupdf::ll_fz_drop_path);
        mupdf::ll_fz_rectto(white.get(),area.x0,area.y0,area.x1,area.y1);const float c[]={1,1,1};
        mupdf::ll_fz_fill_path(dev.get(),white.get(),0,identity,mupdf::ll_fz_device_rgb(),c,1,default_params);
        mupdf::ll_fz_pop_clip(dev.get());
    }
    mupdf::ll_fz_close_device(dev.get());
    if(pix->n!=4||pix->stride<w*4)throw std::runtime_error("native raster layout");
    if(mode==2||mode==3) {Result p;rect(p,area);event(out,13,p);}
    Result p;matrix(p,fz_matrix{float(w/scale),0,0,float(h/scale),float(box.x0/scale),float(box.y0/scale)});
    uint32_t preparation=0;const auto source_kind=job.records[start]->kind;
    // High image-flag bits describe actual preparation, not GPU drawing.
    if(source_kind==8)preparation|=0x100;       // CPU shading bitmap.
    if(source_kind==15)preparation|=0x200;     // CPU composite region.
    if(source_kind==17)preparation|=0x4000;    // CPU pattern bitmap.
    if(source_kind>=4&&source_kind<=7)preparation|=0x1000; // Glyph fallback.
    if(mode==2||mode==3||source_kind==13)preparation|=0x400; // Mask coverage.
    if(source_kind==13&&mode==1)preparation|=0x800; // Single image alpha.
    put(p,uint32_t(w));put(p,uint32_t(h));put(p,uint32_t(w*4));put(p,uint32_t(1)|preparation);
    for(int y=0;y<h;++y)blob(p,pix->samples+y*pix->stride,size_t(w)*4);
    event(out,9,p);
    if(mode==2||mode==3)event(out,14,Result{});
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
    const double tw=std::max(1.,std::min(double(image->image->w),std::ceil(std::hypot(m.a,m.b)*density)));
    const double th=std::max(1.,std::min(double(image->image->h),std::ceil(std::hypot(m.c,m.d)*density)));
    const int x0=int(std::floor(std::clamp(double(local.x0),0.,1.)*tw));
    const int y0=int(std::floor(std::clamp(double(local.y0),0.,1.)*th));
    const int x1=int(std::ceil(std::clamp(double(local.x1),0.,1.)*tw));
    const int y1=int(std::ceil(std::clamp(double(local.y1),0.,1.)*th));
    const int w=x1-x0,h=y1-y0;if(w<=0||h<=0)return;
    if(w>32768||h>32768||int64_t(w)*h>16*1024*1024)throw std::runtime_error("native image budget");
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
void materialize(Job& job,Result& out,const Record& r,fz_rect area) {
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
        // Clip outlines are merged in page space; fills retain reusable glyph space.
        struct Glyph {const Result* bytes;fz_matrix m;};std::vector<Glyph> glyphs;
        for(auto* s=r.text->head;s;s=s->next)for(int i=0;i<s->len;++i) {
            auto item=s->items[i];if(item.gid==-1)continue;
            int gid=item.gid<0?mupdf::ll_fz_encode_character(s->font,item.ucs):item.gid;
            auto key=std::make_pair(s->font,gid);auto found=job.glyphs.find(key);
            if(found==job.glyphs.end()) {
                std::unique_ptr<fz_path,void(*)(const fz_path*)> p(mupdf::ll_fz_outline_glyph(s->font,gid,identity),mupdf::ll_fz_drop_path);
                if(!p)throw std::runtime_error("font has no vector outline");
                auto bytes=path_bytes(p.get());job.glyph_bytes+=bytes.bytes.size();
                if(job.glyph_bytes>128*1024*1024)throw std::runtime_error("native glyph budget exceeded");
                found=job.glyphs.emplace(key,std::move(bytes)).first;
            }
            auto m=s->trm;m.e=item.x;m.f=item.y;glyphs.push_back({&found->second,r.kind==4?mupdf::ll_fz_concat(m,r.matrix):m});
        }
        if(r.kind==4)for(const auto& glyph:glyphs) {
            // A borrowed temporary record must not drop the original resources.
            Record paint;paint.kind=0;paint.alpha=r.alpha;paint.params=r.params;paint.cs=mupdf::ll_fz_keep_colorspace(r.cs);
            std::copy(r.color,r.color+FZ_MAX_COLORS,paint.color);path_event(out,paint,*glyph.bytes,glyph.m,true);
        } else {
            Result merged;
            for(const auto& glyph:glyphs) {
                const auto& b=glyph.bytes->bytes;size_t at=0;
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
    if(r.kind==15){put(p,double(r.alpha));put(p,uint32_t(r.blend));put(p,uint32_t(r.isolated));put(p,uint32_t(r.knockout));}
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

extern "C" __declspec(dllexport) int leaflet_scene_probe(fz_page* page,uint64_t* score,uint64_t* operations) noexcept {
    using namespace leaflet_scene;
    try {if(!page||!score||!operations)return 0;Job job;job.count_only=true;
        std::unique_ptr<fz_device,DevDrop> dev(leaflet_scene_device(job));
        mupdf::ll_fz_run_page(page,dev.get(),identity,&job.cookie);mupdf::ll_fz_close_device(dev.get());
        *score=job.score;*operations=job.operations;return 1;
    }catch(...){return 0;}
}

extern "C" __declspec(dllexport) void leaflet_scene_drop(leaflet_scene::Job* job) noexcept {delete job;}
extern "C" __declspec(dllexport) uint32_t leaflet_scene_abi() noexcept{return 1;}
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
        for(const auto& r:job->records){put(job->metadata,r->kind);
            const uint32_t flags=r->image?(uint32_t(std::min(r->image->w,65535))|(uint32_t(std::min(r->image->h,65535))<<16)):
                r->shade?(gradient(r->shade)?uint32_t(r->shade->type):0u):r->flags;
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
            if(start>last||last>=job->records.size()||mode>6||mode==4)throw std::runtime_error("invalid native request");
            if(mode>=5)raster_image(*job,*out,start,last,fz_rect{float(x0),float(y0),float(x1),float(y1)},scale);
            else if(mode)raster(*job,*out,start,last,mode,fz_rect{float(x0),float(y0),float(x1),float(y1)},scale);
            else {
                const auto& r=*job->records[start];
                try {materialize(*job,*out,r,fz_rect{float(x0),float(y0),float(x1),float(y1)});}
                catch(const std::runtime_error& e) {
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
