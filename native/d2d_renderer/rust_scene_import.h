// Thin, checked LFSC v2 upload adapter. Scene policy and validation live in Rust.
#include <array>
#include <map>
#include <optional>
#include <stdexcept>
namespace leaflet_rust_upload {
struct Reader {
    const uint8_t* p;size_t left;
    const uint8_t* take(size_t size){if(size>left)throw std::runtime_error("truncated scene");auto* value=p;p+=size;left-=size;return value;}
    template<class T>T value(){T result;std::memcpy(&result,take(sizeof(T)),sizeof(T));return result;}
    bool boolean(){auto v=value<uint8_t>();if(v>1)throw std::runtime_error("invalid bool");return v!=0;}
    size_t count(size_t limit){auto v=value<uint64_t>();if(v>limit)throw std::runtime_error("scene count limit");return static_cast<size_t>(v);}
    float number(){const auto result=static_cast<float>(value<double>());if(!std::isfinite(result))throw std::runtime_error("non-finite GPU value");return result;}
};
struct Resource {uint32_t kind=0,w=0,h=0,stride=0;const uint8_t* bytes=nullptr;size_t size=0;};
struct Program {
    void* surface;std::vector<Resource> resources;
    std::vector<void*> paths,bitmaps,styles;
    std::map<std::pair<uint32_t,bool>,void*> path_index;
    std::map<uint32_t,void*> image_index;
    std::vector<SpdfD2DSceneCommand> commands;
    std::vector<std::vector<SpdfD2DGradientStop>> stops;
    std::vector<std::vector<float>> tables;
    explicit Program(void* s):surface(s){}
    ~Program(){for(auto p:paths)spdf_d2d_destroy_path(p);for(auto p:bitmaps)spdf_d2d_destroy_bitmap(p);for(auto p:styles)spdf_d2d_destroy_stroke_style(p);}
    static void check(int32_t hr){if(hr<0)throw std::runtime_error("native resource creation failed");}
    const Resource& get(uint32_t index,uint32_t kind){if(index>=resources.size()||resources[index].kind!=kind)throw std::runtime_error("invalid resource");return resources[index];}
    void* path(uint32_t index,bool even){
        const auto key=std::make_pair(index,even);auto found=path_index.find(key);if(found!=path_index.end())return found->second;
        const auto& resource=get(index,0);Reader reader{resource.bytes,resource.size};std::vector<SpdfD2DPathCommand> list;
        while(reader.left){if(list.size()>=1048576)throw std::runtime_error("path segment limit");SpdfD2DPathCommand command{};command.type=reader.value<uint8_t>();
            const size_t n=command.type==1||command.type==2?2:command.type==3?6:command.type==4?0:99;
            if(n==99)throw std::runtime_error("invalid path tag");for(size_t i=0;i<n;++i)command.points[i]=reader.number();list.push_back(command);
        }
        void* result=nullptr;check(spdf_d2d_create_path(surface,list.data(),static_cast<uint32_t>(list.size()),even?1u:0u,&result));
        paths.push_back(result);path_index[key]=result;return result;
    }
    void* bitmap(uint32_t index){auto found=image_index.find(index);if(found!=image_index.end())return found->second;
        const auto& resource=get(index,1);void* result=nullptr;check(spdf_d2d_create_bitmap(surface,resource.bytes,resource.w,resource.h,resource.stride,&result));
        bitmaps.push_back(result);image_index[index]=result;return result;
    }
    void* style(Reader& reader){if(!reader.boolean())return nullptr;
        const auto start=reader.value<uint32_t>(),dash=reader.value<uint32_t>(),end=reader.value<uint32_t>(),join=reader.value<uint32_t>();
        const auto miter=reader.number(),phase=reader.number();const auto count=reader.count(4096);std::vector<float> dashes(count);for(auto& value:dashes)value=reader.number();
        void* result=nullptr;check(spdf_d2d_create_stroke_style(surface,start,dash,end,join,miter,phase,dashes.data(),static_cast<uint32_t>(count),&result));
        styles.push_back(result);return result;
    }
    void gradient(Reader& reader,SpdfD2DSceneCommand& command){
        const auto count=reader.count(65536);stops.emplace_back(count);for(auto& stop:stops.back()){stop.position=reader.number();stop.argb=reader.value<uint32_t>();}
        command.data=stops.back().data();command.data_count=static_cast<uint32_t>(count);
    }
    void load(Reader& reader,float width,float height){
        const auto count=reader.count(1048576);resources.reserve(count);size_t total=0,images=0;
        for(size_t i=0;i<count;++i){Resource resource;resource.kind=reader.value<uint32_t>();if(resource.kind>1)throw std::runtime_error("invalid resource type");
            resource.size=reader.count(128*1024*1024);resource.bytes=reader.take(resource.size);
            total+=resource.size;if(total>128*1024*1024)throw std::runtime_error("resource budget");
            if(resource.kind==1){resource.w=reader.value<uint32_t>();resource.h=reader.value<uint32_t>();resource.stride=reader.value<uint32_t>();
                if(resource.w==0||resource.h==0||uint64_t(resource.w)*4>resource.stride||uint64_t(resource.h)*resource.stride!=resource.size)throw std::runtime_error("invalid image");
                images+=resource.size;if(images>64*1024*1024)throw std::runtime_error("image budget");}
            resources.push_back(resource);
        }
        SpdfD2DSceneCommand clear{};clear.type=1;clear.values[2]=width;clear.values[3]=height;clear.uint_values[0]=0xffffffff;commands.push_back(clear);
        const auto length=reader.count(1048576);commands.reserve(length*2+1);
        for(size_t i=0;i<length;++i){
            SpdfD2DSceneCommand command{};const auto operation=reader.value<uint32_t>();std::optional<uint32_t> stroke_color;uint32_t clip_id=0;bool clip_even=false;
            switch(operation){
            case 0:{const auto id=reader.value<uint32_t>();const bool fill=reader.boolean();if(fill)command.uint_values[0]=reader.value<uint32_t>();
                if(reader.boolean())stroke_color=reader.value<uint32_t>();command.values[0]=reader.number();command.stroke_style=style(reader);
                const bool even=reader.boolean();reader.boolean();reader.boolean();reader.boolean();command.resource=path(id,even);command.type=fill?15u:0u;break;}
            case 1:{clip_id=reader.value<uint32_t>();clip_even=reader.boolean();command.type=8;break;}
            case 2:{const auto id=reader.value<uint32_t>();const auto thickness=reader.number();auto* stroke_style=style(reader);void* expanded=nullptr;
                check(spdf_d2d_create_stroked_path(surface,path(id,false),thickness,stroke_style,&expanded));paths.push_back(expanded);command.resource=expanded;command.type=8;break;}
            case 3:{command.resource=bitmap(reader.value<uint32_t>());command.type=14;command.values[2]=1;command.values[3]=1;command.values[4]=reader.number();command.uint_values[0]=reader.boolean()?1u:0u;break;}
            case 4:case 5:{const auto id=reader.value<uint32_t>();command.type=operation==4?17u:18u;const size_t n=operation==4?4:6;
                for(size_t j=0;j<n;++j)command.values[j]=reader.number();gradient(reader,command);const bool even=reader.boolean();command.resource=path(id,even);break;}
            case 6:{command.type=6;command.values[0]=reader.number();command.uint_values[0]=reader.value<uint32_t>();const bool isolated=reader.boolean(),knockout=reader.boolean();command.uint_values[1]=(knockout?1u:0u)|(isolated?0u:2u);break;}
            case 7:command.type=7;break;
            case 8:command.type=12;for(size_t j=0;j<4;++j)command.values[j]=reader.number();command.uint_values[0]=reader.boolean()?1u:0u;command.uint_values[1]=reader.value<uint32_t>();break;
            case 9:{command.type=13;const auto n=reader.count(65536);tables.emplace_back(n);for(auto& value:tables.back())value=reader.number();command.data=tables.back().data();command.data_count=static_cast<uint32_t>(n);break;}
            case 10:command.type=9;break;
            case 11:{const auto n=reader.count(1048576);std::vector<void*> sources(n);std::vector<SpdfD2DTransform> matrices(n);
                std::vector<uint32_t> indices(n);for(size_t j=0;j<n;++j){indices[j]=reader.value<uint32_t>();std::array<float,6> values{};for(auto& v:values)v=reader.number();std::memcpy(&matrices[j],values.data(),sizeof(matrices[j]));}
                command.uint_values[0]=reader.value<uint32_t>();const bool even=reader.boolean();for(size_t j=0;j<n;++j)sources[j]=path(indices[j],even);
                void* group=nullptr;check(spdf_d2d_create_geometry_group(surface,sources.data(),matrices.data(),static_cast<uint32_t>(n),even?1u:0u,&group));paths.push_back(group);command.resource=group;command.type=15;break;}
            default:throw std::runtime_error("invalid operation");
            }
            std::array<float,6> matrix{};for(auto& value:matrix)value=reader.number();command.flags=1;
            static_assert(sizeof(command.transform)==sizeof(matrix),"transform ABI");std::memcpy(&command.transform,matrix.data(),sizeof(matrix));
            if(reader.boolean())reader.take(4*sizeof(double));if(reader.boolean())reader.value<uint32_t>();if(reader.boolean())reader.value<uint32_t>();reader.value<uint32_t>();
            const auto opcode=reader.value<uint32_t>();
            const bool axis=reader.boolean();std::array<float,4> rect{};if(axis)for(auto& value:rect)value=reader.number();
            if(operation==1||operation==2){if(opcode!=2&&opcode!=8&&!(operation==1&&opcode==19&&axis))throw std::runtime_error("invalid clip opcode");command.type=opcode;
                if(operation==1){if(opcode==19){for(size_t j=0;j<4;++j)command.values[j]=rect[j];}else{command.resource=path(clip_id,clip_even);}}}
            if(operation==6||operation==7||operation==10){
                const bool valid=operation==6?(opcode==4||opcode==6):operation==7?(opcode==5||opcode==7):(opcode==3||opcode==9||opcode==20);
                if(!valid)throw std::runtime_error("invalid scope opcode");command.type=opcode;
            }
            if(command.type)commands.push_back(command);
            if(stroke_color){command.type=16;command.uint_values[0]=*stroke_color;commands.push_back(command);}
        }
        reader.value<uint64_t>();reader.value<uint64_t>();if(reader.left)throw std::runtime_error("trailing scene bytes");
    }
};
}

extern "C" __declspec(dllexport) int32_t spdf_d2d_import_rust_scene(void* surface,const void* bytes,size_t size,float width,float height,void** output) noexcept {
    if(!surface||!bytes||!output||size<8||size>256*1024*1024||!std::isfinite(width)||!std::isfinite(height)||width<=0||height<=0)return static_cast<int32_t>(E_INVALIDARG);
    *output=nullptr;
    try {
        leaflet_rust_upload::Reader reader{static_cast<const uint8_t*>(bytes),size};
        if(std::memcmp(reader.take(8),"LFSC\x02\0\0\0",8)!=0)return static_cast<int32_t>(E_INVALIDARG);
        leaflet_rust_upload::Program program(surface);program.load(reader,width,height);
        return spdf_d2d_create_scene(surface,program.commands.data(),static_cast<uint32_t>(program.commands.size()),output);
    } catch(...){return static_cast<int32_t>(E_INVALIDARG);}
}
