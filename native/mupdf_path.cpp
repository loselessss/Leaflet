// Built against the exact headers/import library shipped with PyMuPDF.
#pragma warning(push)
#pragma warning(disable: 4100 4611) // Warnings in upstream inline headers only.
#include "mupdf/functions.h"
#pragma warning(pop)
#include <cstdint>
#include <cstring>
#include <vector>
#include <new>

struct Result { std::vector<unsigned char> bytes; size_t count=0; bool failed=false; };
static void append(void* opaque, unsigned char tag, const float* coordinates, size_t count) noexcept {
    auto& result=*static_cast<Result*>(opaque);
    if (result.failed) return;
    try {
        if (result.bytes.size()+1+count*8 > 16*1024*1024) { result.failed=true; return; }
        result.bytes.push_back(tag);
        for(size_t i=0;i<count;++i) {
            double number=coordinates[i]; unsigned char bytes[8];
            std::memcpy(bytes,&number,8);
            result.bytes.insert(result.bytes.end(),bytes,bytes+8);
        }
        ++result.count;
    } catch (...) { result.failed=true; }
}
static void move(fz_context*,void* arg,float x,float y) {float v[]={x,y};append(arg,1,v,2);}
static void line(fz_context*,void* arg,float x,float y) {float v[]={x,y};append(arg,2,v,2);}
static void cubic(fz_context*,void* arg,float a,float b,float c,float d,float e,float f) {
    float v[]={a,b,c,d,e,f};append(arg,3,v,6);
}
static void close(fz_context*,void* arg) {append(arg,4,nullptr,0);}
extern "C" __declspec(dllexport) const char* leaflet_path_version() {return FZ_VERSION;}
extern "C" __declspec(dllexport) void leaflet_path_drop(Result* result) {delete result;}
extern "C" __declspec(dllexport) Result* leaflet_path_walk(const fz_path* path,
    const unsigned char** data,size_t* size,size_t* count) noexcept {
    if(!path || !data || !size || !count) return nullptr;
    Result* result=nullptr;
    try {
        result=new Result();
        const fz_path_walker walker={move,line,cubic,close,nullptr,nullptr,nullptr,nullptr};
        mupdf::ll_fz_walk_path(path,&walker,result);
        if(result->failed) {delete result;return nullptr;}
        *data=result->bytes.data(); *size=result->bytes.size(); *count=result->count;
        return result;
    } catch (...) {delete result;return nullptr;}
}

extern "C" __declspec(dllexport) Result* leaflet_text_scan(const fz_text* text,
    const float* matrix, const unsigned char** data,size_t* size,size_t* count) noexcept {
    if(!text || !matrix || !data || !size || !count) return nullptr;
    Result* result=nullptr;
    try {
        result=new Result();
        const fz_matrix page={matrix[0],matrix[1],matrix[2],matrix[3],matrix[4],matrix[5]};
        for(auto* span=text->head;span;span=span->next) {
            for(int index=0;index<span->len;++index) {
                const auto& item=span->items[index];
                if(item.gid==-1) continue;
                // Preserve Python's cmap/invisible-codepoint recovery path.
                if(item.gid<0 || result->bytes.size()+40 > 16*1024*1024) {
                    delete result;return nullptr;
                }
                fz_matrix local=span->trm;local.e=item.x;local.f=item.y;
                const fz_matrix transformed=mupdf::ll_fz_concat(local,page);
                static_assert(sizeof(fz_matrix)==24,"matrix record ABI");
                const uint64_t font=reinterpret_cast<uintptr_t>(span->font);
                const int32_t gid=item.gid,ucs=item.ucs;
                const auto add=[&](const void* pointer,size_t length) {
                    const auto* bytes=static_cast<const unsigned char*>(pointer);
                    result->bytes.insert(result->bytes.end(),bytes,bytes+length);
                };
                add(&font,8);add(&gid,4);add(&ucs,4);add(&transformed,24);
                ++result->count;
            }
        }
        *data=result->bytes.data();*size=result->bytes.size();*count=result->count;return result;
    } catch(...) {delete result;return nullptr;}
}

extern "C" __declspec(dllexport) Result* leaflet_glyph_walk(fz_font* font,int gid,
    const unsigned char** data,size_t* size,size_t* count) noexcept {
    if(!font || gid<0) return nullptr;
    fz_path* path=nullptr;
    try {
        path=mupdf::ll_fz_outline_glyph(font,gid,fz_matrix{1,0,0,1,0,0});
        if(!path) return nullptr;
        Result* result=leaflet_path_walk(path,data,size,count);
        mupdf::ll_fz_drop_path(path);
        return result;
    } catch(...) {
        if(path) mupdf::ll_fz_drop_path(path);
        return nullptr;
    }
}

#include "mupdf_scene.h"
