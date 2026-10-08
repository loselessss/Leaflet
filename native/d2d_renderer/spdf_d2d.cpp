#define SPDF_D2D_EXPORTS
#include "spdf_d2d.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <iterator>
#include <memory>
#include <new>
#include <unordered_map>
#include <utility>
#include <vector>

#include <d2d1_1.h>
#include <d2d1_2.h>
#include <d2d1_3.h>
#include <d2d1effects.h>
#include <d2d1effects_2.h>
#include <d3d11_1.h>
#include <dwrite.h>
#include <dxgi1_2.h>
#include <dxgi1_4.h>
#include <wrl/client.h>

using Microsoft::WRL::ComPtr;

namespace {

struct Scene;

HRESULT create_d3d_device(
    D3D_DRIVER_TYPE driver_type,
    ComPtr<ID3D11Device>& device,
    D3D_FEATURE_LEVEL& selected_level) noexcept {
    constexpr D3D_FEATURE_LEVEL levels[] = {
        D3D_FEATURE_LEVEL_11_1,
        D3D_FEATURE_LEVEL_11_0,
        D3D_FEATURE_LEVEL_10_1,
        D3D_FEATURE_LEVEL_10_0,
    };
    ComPtr<ID3D11DeviceContext> immediate_context;
    auto result = D3D11CreateDevice(
        nullptr,
        driver_type,
        nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT,
        levels,
        static_cast<UINT>(std::size(levels)),
        D3D11_SDK_VERSION,
        &device,
        &selected_level,
        &immediate_context);
    if (result == E_INVALIDARG) {
        // Windows 7 without the 11.1 runtime rejects 11_1 in the list.
        result = D3D11CreateDevice(
            nullptr,
            driver_type,
            nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            levels + 1,
            static_cast<UINT>(std::size(levels) - 1),
            D3D11_SDK_VERSION,
            &device,
            &selected_level,
            &immediate_context);
    }
    return result;
}

void reset_info(SpdfD2DInfo* info) noexcept {
    if (info == nullptr) {
        return;
    }
    const auto caller_size = info->struct_size;
    std::memset(info, 0, std::min<std::size_t>(caller_size, sizeof(SpdfD2DInfo)));
    info->struct_size = sizeof(SpdfD2DInfo);
    info->abi_version = SPDF_D2D_ABI_VERSION;
}

void set_adapter_name(ID3D11Device* device, SpdfD2DInfo* info) noexcept {
    if (device == nullptr || info == nullptr) {
        return;
    }
    ComPtr<IDXGIDevice> dxgi_device;
    if (FAILED(device->QueryInterface(IID_PPV_ARGS(&dxgi_device)))) {
        return;
    }
    ComPtr<IDXGIAdapter> adapter;
    if (FAILED(dxgi_device->GetAdapter(&adapter))) {
        return;
    }
    DXGI_ADAPTER_DESC description{};
    if (FAILED(adapter->GetDesc(&description))) {
        return;
    }
    wcsncpy_s(
        info->adapter_name,
        SPDF_D2D_ADAPTER_NAME_LENGTH,
        description.Description,
        _TRUNCATE);
}

class Surface {
public:
    struct Bitmap {
        Surface* owner;
        ComPtr<ID2D1Bitmap1> resource;
    };

    struct Path {
        Surface* owner;
        ComPtr<ID2D1Geometry> resource;
        ComPtr<ID2D1GeometryRealization> fill_realization;
    };

    struct StrokeStyle {
        Surface* owner;
        ComPtr<ID2D1StrokeStyle1> resource;
    };

    HRESULT initialize(
        HWND hwnd,
        std::uint32_t width,
        std::uint32_t height,
        float dpi,
        SpdfD2DInfo* info) noexcept {
        D3D_FEATURE_LEVEL feature_level = D3D_FEATURE_LEVEL_10_0;
        auto result = create_d3d_device(
            D3D_DRIVER_TYPE_HARDWARE, d3d_device_, feature_level);
        if (SUCCEEDED(result)) {
            driver_ = SPDF_D2D_DRIVER_HARDWARE;
        } else {
            result = create_d3d_device(D3D_DRIVER_TYPE_WARP, d3d_device_, feature_level);
            if (FAILED(result)) {
                return result;
            }
            driver_ = SPDF_D2D_DRIVER_WARP;
        }
        feature_level_ = feature_level;

        result = d3d_device_.As(&dxgi_device_);
        if (FAILED(result)) {
            return result;
        }
        ComPtr<IDXGIAdapter> adapter;
        result = dxgi_device_->GetAdapter(&adapter);
        if (FAILED(result)) {
            return result;
        }
        result = adapter->GetParent(IID_PPV_ARGS(&dxgi_factory_));
        if (FAILED(result)) {
            return result;
        }

        D2D1_FACTORY_OPTIONS options{};
        result = D2D1CreateFactory(
            D2D1_FACTORY_TYPE_SINGLE_THREADED,
            __uuidof(ID2D1Factory1),
            &options,
            reinterpret_cast<void**>(d2d_factory_.GetAddressOf()));
        if (FAILED(result)) {
            return result;
        }
        result = d2d_factory_->CreateDevice(dxgi_device_.Get(), &d2d_device_);
        if (FAILED(result)) {
            return result;
        }
        result = d2d_device_->CreateDeviceContext(
            D2D1_DEVICE_CONTEXT_OPTIONS_NONE, &d2d_context_);
        if (FAILED(result)) {
            return result;
        }
        configure_antialiasing();
        // Geometry realizations cache tessellation for repeated zoom/pan frames.
        // They are optional and FillGeometry remains the compatibility path.
        d2d_context_.As(&d2d_context1_);
        result = DWriteCreateFactory(
            DWRITE_FACTORY_TYPE_SHARED,
            __uuidof(IDWriteFactory),
            reinterpret_cast<IUnknown**>(dwrite_factory_.GetAddressOf()));
        if (FAILED(result)) {
            return result;
        }

        DXGI_SWAP_CHAIN_DESC1 description{};
        description.Width = std::max<std::uint32_t>(1, width);
        description.Height = std::max<std::uint32_t>(1, height);
        description.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        description.SampleDesc.Count = 1;
        description.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        description.BufferCount = 2;
        description.Scaling = DXGI_SCALING_STRETCH;
        description.SwapEffect = DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
        description.AlphaMode = DXGI_ALPHA_MODE_IGNORE;
        result = dxgi_factory_->CreateSwapChainForHwnd(
            d3d_device_.Get(), hwnd, &description, nullptr, nullptr, &swap_chain_);
        if (FAILED(result)) {
            return result;
        }
        dxgi_factory_->MakeWindowAssociation(hwnd, DXGI_MWA_NO_ALT_ENTER);
        dpi_ = dpi > 0 ? dpi : 96.0f;
        result = create_target();
        if (SUCCEEDED(result) && info != nullptr) {
            info->driver = driver_;
            info->feature_level = static_cast<std::uint32_t>(feature_level_);
            set_adapter_name(d3d_device_.Get(), info);
        }
        return result;
    }

    HRESULT resize(std::uint32_t width, std::uint32_t height, float dpi) noexcept {
        if (!swap_chain_ || drawing_ || width == 0 || height == 0) {
            return E_INVALIDARG;
        }
        d2d_context_->SetTarget(nullptr);
        target_.Reset();
        const auto result = swap_chain_->ResizeBuffers(
            0, width, height, DXGI_FORMAT_UNKNOWN, 0);
        if (FAILED(result)) {
            return result;
        }
        dpi_ = dpi > 0 ? dpi : dpi_;
        return create_target();
    }

    HRESULT clear(std::uint32_t argb) noexcept {
        if (!d2d_context_ || !target_ || !swap_chain_) {
            return E_UNEXPECTED;
        }
        auto result = begin_frame(argb);
        if (FAILED(result)) {
            return result;
        }
        return end_frame();
    }

    HRESULT begin_frame(std::uint32_t argb) noexcept {
        if (!d2d_context_ || !target_ || drawing_ || layer_depth_ != 0 ||
                axis_clip_depth_ != 0 || !mask_captures_.empty() ||
                !composite_captures_.empty()) {
            return E_UNEXPECTED;
        }
        const auto alpha = static_cast<float>((argb >> 24) & 0xff) / 255.0f;
        const auto red = static_cast<float>((argb >> 16) & 0xff) / 255.0f;
        const auto green = static_cast<float>((argb >> 8) & 0xff) / 255.0f;
        const auto blue = static_cast<float>(argb & 0xff) / 255.0f;
        d2d_context_->BeginDraw();
        drawing_ = true;
        configure_antialiasing();
        d2d_context_->SetTransform(D2D1::Matrix3x2F::Identity());
        d2d_context_->Clear(D2D1::ColorF(red, green, blue, alpha));
        return S_OK;
    }

    HRESULT set_transform(
        float m11,
        float m12,
        float m21,
        float m22,
        float dx,
        float dy) noexcept {
        if (!d2d_context_ || !drawing_) {
            return E_UNEXPECTED;
        }
        for (const auto& capture : composite_captures_) {
            if (capture.cropped) {
                dx -= capture.destination_origin.x;
                dy -= capture.destination_origin.y;
            }
        }
        d2d_context_->SetTransform(D2D1::Matrix3x2F(
            m11, m12, m21, m22, dx, dy));
        return S_OK;
    }

    HRESULT create_bitmap(
        const void* pixels,
        std::uint32_t width,
        std::uint32_t height,
        std::uint32_t stride,
        Bitmap** bitmap) noexcept {
        if (!d2d_context_ || pixels == nullptr || width == 0 || height == 0 ||
                stride < width * 4 || bitmap == nullptr) {
            return E_INVALIDARG;
        }
        *bitmap = nullptr;
        auto result_bitmap = new (std::nothrow) Bitmap{this, nullptr};
        if (result_bitmap == nullptr) {
            return E_OUTOFMEMORY;
        }
        const auto properties = D2D1::BitmapProperties1(
            D2D1_BITMAP_OPTIONS_NONE,
            D2D1::PixelFormat(
                DXGI_FORMAT_B8G8R8A8_UNORM,
                D2D1_ALPHA_MODE_PREMULTIPLIED),
            96.0f,
            96.0f);
        const auto result = d2d_context_->CreateBitmap(
            D2D1::SizeU(width, height),
            pixels,
            stride,
            &properties,
            &result_bitmap->resource);
        if (FAILED(result)) {
            delete result_bitmap;
            return result;
        }
        *bitmap = result_bitmap;
        return S_OK;
    }

    HRESULT create_path(
        const SpdfD2DPathCommand* commands,
        std::uint32_t command_count,
        bool even_odd,
        Path** path) noexcept {
        if (!d2d_factory_ || commands == nullptr || command_count == 0 || path == nullptr) {
            return E_INVALIDARG;
        }
        *path = nullptr;
        auto result_path = new (std::nothrow) Path{this, nullptr, nullptr};
        if (result_path == nullptr) {
            return E_OUTOFMEMORY;
        }
        ComPtr<ID2D1PathGeometry> geometry;
        auto result = d2d_factory_->CreatePathGeometry(&geometry);
        ComPtr<ID2D1GeometrySink> sink;
        if (SUCCEEDED(result)) {
            result = geometry->Open(&sink);
        }
        if (FAILED(result)) {
            delete result_path;
            return result;
        }
        sink->SetFillMode(even_odd ? D2D1_FILL_MODE_ALTERNATE : D2D1_FILL_MODE_WINDING);
        bool figure_open = false;
        for (std::uint32_t index = 0; index < command_count; ++index) {
            const auto& command = commands[index];
            switch (command.type) {
            case SPDF_D2D_PATH_MOVE:
                if (figure_open) {
                    sink->EndFigure(D2D1_FIGURE_END_OPEN);
                }
                sink->BeginFigure(
                    D2D1::Point2F(command.points[0], command.points[1]),
                    D2D1_FIGURE_BEGIN_FILLED);
                figure_open = true;
                break;
            case SPDF_D2D_PATH_LINE:
                if (!figure_open) {
                    result = E_INVALIDARG;
                    break;
                }
                sink->AddLine(D2D1::Point2F(command.points[0], command.points[1]));
                break;
            case SPDF_D2D_PATH_CUBIC:
                if (!figure_open) {
                    result = E_INVALIDARG;
                    break;
                }
                sink->AddBezier(D2D1::BezierSegment(
                    D2D1::Point2F(command.points[0], command.points[1]),
                    D2D1::Point2F(command.points[2], command.points[3]),
                    D2D1::Point2F(command.points[4], command.points[5])));
                break;
            case SPDF_D2D_PATH_CLOSE:
                if (!figure_open) {
                    result = E_INVALIDARG;
                    break;
                }
                sink->EndFigure(D2D1_FIGURE_END_CLOSED);
                figure_open = false;
                break;
            default:
                result = E_INVALIDARG;
                break;
            }
            if (FAILED(result)) {
                break;
            }
        }
        if (figure_open) {
            sink->EndFigure(D2D1_FIGURE_END_OPEN);
        }
        if (SUCCEEDED(result)) {
            result = sink->Close();
        }
        if (FAILED(result)) {
            delete result_path;
            return result;
        }
        result_path->resource = geometry;
        realize_path(result_path);
        *path = result_path;
        return S_OK;
    }

    HRESULT create_geometry_group(
        Path* const* paths,
        const SpdfD2DTransform* transforms,
        std::uint32_t path_count,
        bool even_odd,
        Path** group) noexcept {
        if (!d2d_factory_ || paths == nullptr || transforms == nullptr ||
                path_count == 0 || group == nullptr) {
            return E_INVALIDARG;
        }
        *group = nullptr;
        std::vector<ComPtr<ID2D1TransformedGeometry>> transformed;
        std::vector<ID2D1Geometry*> geometries;
        transformed.reserve(path_count);
        geometries.reserve(path_count);
        for (std::uint32_t index = 0; index < path_count; ++index) {
            const auto path = paths[index];
            if (path == nullptr || path->owner != this || !path->resource) {
                return E_INVALIDARG;
            }
            const auto& matrix = transforms[index];
            ComPtr<ID2D1TransformedGeometry> instance;
            const auto d2d_matrix = D2D1::Matrix3x2F(
                matrix.m11, matrix.m12, matrix.m21, matrix.m22,
                matrix.dx, matrix.dy);
            const auto result = d2d_factory_->CreateTransformedGeometry(
                path->resource.Get(),
                &d2d_matrix,
                &instance);
            if (FAILED(result)) {
                return result;
            }
            geometries.push_back(instance.Get());
            transformed.push_back(std::move(instance));
        }
        auto result_group = new (std::nothrow) Path{this, nullptr, nullptr};
        if (result_group == nullptr) {
            return E_OUTOFMEMORY;
        }
        ComPtr<ID2D1GeometryGroup> geometry_group;
        const auto result = d2d_factory_->CreateGeometryGroup(
            even_odd ? D2D1_FILL_MODE_ALTERNATE : D2D1_FILL_MODE_WINDING,
            geometries.data(), path_count, &geometry_group);
        if (FAILED(result)) {
            delete result_group;
            return result;
        }
        result_group->resource = geometry_group;
        realize_path(result_group);
        *group = result_group;
        return S_OK;
    }

    HRESULT create_stroke_style(
        std::uint32_t start_cap,
        std::uint32_t dash_cap,
        std::uint32_t end_cap,
        std::uint32_t line_join,
        float miter_limit,
        float dash_offset,
        const float* dashes,
        std::uint32_t dash_count,
        StrokeStyle** stroke_style) noexcept {
        if (!d2d_factory_ || stroke_style == nullptr ||
                !std::isfinite(miter_limit) || miter_limit < 1.0f ||
                !std::isfinite(dash_offset) ||
                (dash_count != 0 && dashes == nullptr)) {
            return E_INVALIDARG;
        }
        const auto cap = [](std::uint32_t value, D2D1_CAP_STYLE* result) {
            switch (value) {
            case 0: *result = D2D1_CAP_STYLE_FLAT; return true;
            case 1: *result = D2D1_CAP_STYLE_ROUND; return true;
            case 2: *result = D2D1_CAP_STYLE_SQUARE; return true;
            case 3: *result = D2D1_CAP_STYLE_TRIANGLE; return true;
            default: return false;
            }
        };
        D2D1_CAP_STYLE start{};
        D2D1_CAP_STYLE dash{};
        D2D1_CAP_STYLE end{};
        if (!cap(start_cap, &start) || !cap(dash_cap, &dash) ||
                !cap(end_cap, &end)) {
            return E_INVALIDARG;
        }
        D2D1_LINE_JOIN join{};
        switch (line_join) {
        case 0: join = D2D1_LINE_JOIN_MITER; break;
        case 1: join = D2D1_LINE_JOIN_ROUND; break;
        case 2: join = D2D1_LINE_JOIN_BEVEL; break;
        case 3: join = D2D1_LINE_JOIN_MITER_OR_BEVEL; break;
        default: return E_INVALIDARG;
        }
        for (std::uint32_t index = 0; index < dash_count; ++index) {
            if (!std::isfinite(dashes[index]) || dashes[index] < 0.0f) {
                return E_INVALIDARG;
            }
        }
        auto created = new (std::nothrow) StrokeStyle{this, nullptr};
        if (created == nullptr) {
            return E_OUTOFMEMORY;
        }
        D2D1_STROKE_STYLE_PROPERTIES1 properties{};
        properties.startCap = start;
        properties.endCap = end;
        properties.dashCap = dash;
        properties.lineJoin = join;
        properties.miterLimit = miter_limit;
        properties.dashStyle = dash_count == 0
            ? D2D1_DASH_STYLE_SOLID : D2D1_DASH_STYLE_CUSTOM;
        properties.dashOffset = dash_offset;
        properties.transformType = D2D1_STROKE_TRANSFORM_TYPE_NORMAL;
        const auto result = d2d_factory_->CreateStrokeStyle(
            properties, dashes, dash_count, &created->resource);
        if (FAILED(result)) {
            delete created;
            return result;
        }
        *stroke_style = created;
        return S_OK;
    }

    HRESULT create_stroked_path(
        Path* path,
        float width,
        StrokeStyle* stroke_style,
        Path** stroked_path) noexcept {
        if (!d2d_factory_ || path == nullptr || path->owner != this ||
                !path->resource || width < 0.0f || stroked_path == nullptr ||
                (stroke_style != nullptr &&
                 (stroke_style->owner != this || !stroke_style->resource))) {
            return E_INVALIDARG;
        }
        *stroked_path = nullptr;
        auto created = new (std::nothrow) Path{this, nullptr, nullptr};
        if (created == nullptr) {
            return E_OUTOFMEMORY;
        }
        ComPtr<ID2D1PathGeometry> geometry;
        auto result = d2d_factory_->CreatePathGeometry(&geometry);
        ComPtr<ID2D1GeometrySink> sink;
        if (SUCCEEDED(result)) {
            result = geometry->Open(&sink);
        }
        if (SUCCEEDED(result)) {
            result = path->resource->Widen(
                width,
                stroke_style == nullptr ? nullptr : stroke_style->resource.Get(),
                nullptr,
                sink.Get());
        }
        if (SUCCEEDED(result)) {
            result = sink->Close();
        }
        if (FAILED(result)) {
            delete created;
            return result;
        }
        created->resource = geometry;
        realize_path(created);
        *stroked_path = created;
        return S_OK;
    }

    HRESULT push_clip_path(Path* path) noexcept {
        if (!drawing_ || path == nullptr || path->owner != this ||
                !path->resource) {
            return E_INVALIDARG;
        }
        const auto parameters = D2D1::LayerParameters1(
            D2D1::InfiniteRect(),
            path->resource.Get(),
            D2D1_ANTIALIAS_MODE_PER_PRIMITIVE,
            D2D1::Matrix3x2F::Identity(),
            1.0f,
            nullptr,
            D2D1_LAYER_OPTIONS1_NONE);
        d2d_context_->PushLayer(parameters, nullptr);
        ++layer_depth_;
        layer_brushes_.emplace_back();
        return S_OK;
    }

    HRESULT push_axis_aligned_clip(
        float left, float top, float right, float bottom) noexcept {
        if (!drawing_ || !std::isfinite(left) || !std::isfinite(top) ||
                !std::isfinite(right) || !std::isfinite(bottom) ||
                right <= left || bottom <= top) {
            return E_INVALIDARG;
        }
        d2d_context_->PushAxisAlignedClip(
            D2D1::RectF(left, top, right, bottom),
            D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
        ++axis_clip_depth_;
        return S_OK;
    }

    HRESULT pop_axis_aligned_clip() noexcept {
        if (!drawing_ || axis_clip_depth_ == 0) return E_UNEXPECTED;
        d2d_context_->PopAxisAlignedClip();
        --axis_clip_depth_;
        return S_OK;
    }

    HRESULT pop_clip() noexcept {
        return pop_layer();
    }

    HRESULT push_opacity_layer(float opacity) noexcept {
        if (!drawing_ || !std::isfinite(opacity) || opacity < 0.0f ||
                opacity > 1.0f) {
            return E_INVALIDARG;
        }
        const auto parameters = D2D1::LayerParameters1(
            D2D1::InfiniteRect(),
            nullptr,
            D2D1_ANTIALIAS_MODE_PER_PRIMITIVE,
            D2D1::Matrix3x2F::Identity(),
            opacity,
            nullptr,
            D2D1_LAYER_OPTIONS1_NONE);
        d2d_context_->PushLayer(parameters, nullptr);
        ++layer_depth_;
        layer_brushes_.emplace_back();
        return S_OK;
    }

    HRESULT begin_mask(
        float left,
        float top,
        float right,
        float bottom,
        bool luminosity,
        std::uint32_t background_argb) noexcept {
        if (!drawing_ || !std::isfinite(left) || !std::isfinite(top) ||
                !std::isfinite(right) || !std::isfinite(bottom) ||
                right <= left || bottom <= top) {
            return E_INVALIDARG;
        }
        MaskCapture capture;
        capture.luminosity = luminosity;
        capture.layer_depth = layer_depth_;
        d2d_context_->GetTarget(&capture.previous_target);
        auto result = d2d_context_->CreateCommandList(&capture.commands);
        if (FAILED(result)) {
            return result;
        }
        d2d_context_->SetTarget(capture.commands.Get());
        mask_captures_.push_back(capture);
        if (luminosity || ((background_argb >> 24) & 0xff) != 0) {
            ComPtr<ID2D1SolidColorBrush> brush;
            result = create_brush(background_argb, &brush);
            if (FAILED(result)) {
                d2d_context_->SetTarget(capture.previous_target.Get());
                mask_captures_.pop_back();
                return result;
            }
            d2d_context_->FillRectangle(
                D2D1::RectF(left, top, right, bottom), brush.Get());
        }
        return S_OK;
    }

    HRESULT apply_alpha_transfer(
        ID2D1Image* source,
        const float* transfer,
        std::uint32_t transfer_count,
        ComPtr<ID2D1Effect>& transfer_effect,
        ComPtr<ID2D1Image>& output) noexcept {
        if (source == nullptr) return E_INVALIDARG;
        output = source;
        if (transfer_count == 0) return S_OK;
        if (transfer == nullptr || transfer_count < 2) return E_INVALIDARG;
        auto result = d2d_context_->CreateEffect(CLSID_D2D1TableTransfer, &transfer_effect);
        if (FAILED(result)) return result;
        transfer_effect->SetInput(0, source);
        if (SUCCEEDED(result)) result = transfer_effect->SetValue(
            D2D1_TABLETRANSFER_PROP_RED_DISABLE, TRUE);
        if (SUCCEEDED(result)) result = transfer_effect->SetValue(
            D2D1_TABLETRANSFER_PROP_GREEN_DISABLE, TRUE);
        if (SUCCEEDED(result)) result = transfer_effect->SetValue(
            D2D1_TABLETRANSFER_PROP_BLUE_DISABLE, TRUE);
        if (SUCCEEDED(result)) result = transfer_effect->SetValue(
            D2D1_TABLETRANSFER_PROP_ALPHA_DISABLE, FALSE);
        if (SUCCEEDED(result)) result = transfer_effect->SetValue(
            D2D1_TABLETRANSFER_PROP_ALPHA_TABLE,
            reinterpret_cast<const BYTE*>(transfer),
            transfer_count * sizeof(float));
        if (SUCCEEDED(result)) result = transfer_effect->SetValue(
            D2D1_TABLETRANSFER_PROP_CLAMP_OUTPUT, TRUE);
        if (SUCCEEDED(result)) transfer_effect->GetOutput(&output);
        return result;
    }

    HRESULT end_mask(
        const float* alpha_transfer = nullptr,
        std::uint32_t transfer_count = 0) noexcept {
        if (!drawing_ || mask_captures_.empty()) {
            return E_UNEXPECTED;
        }
        auto capture = mask_captures_.back();
        mask_captures_.pop_back();
        if (layer_depth_ != capture.layer_depth) {
            d2d_context_->SetTarget(capture.previous_target.Get());
            return E_UNEXPECTED;
        }
        d2d_context_->SetTarget(capture.previous_target.Get());
        auto result = capture.commands->Close();
        if (FAILED(result)) {
            return result;
        }
        ComPtr<ID2D1Image> image = capture.commands;
        ComPtr<ID2D1Effect> luminance, transfer_effect;
        if (capture.luminosity) {
            result = d2d_context_->CreateEffect(
                CLSID_D2D1LuminanceToAlpha, &luminance);
            if (FAILED(result)) {
                return result;
            }
            luminance->SetInput(0, capture.commands.Get());
            luminance->GetOutput(&image);
        }
        result = apply_alpha_transfer(
            image.Get(), alpha_transfer, transfer_count, transfer_effect, image);
        if (FAILED(result)) return result;
        D2D1_RECT_F bounds{};
        result = d2d_context_->GetImageLocalBounds(image.Get(), &bounds);
        if (FAILED(result) || bounds.right <= bounds.left ||
                bounds.bottom <= bounds.top) {
            return FAILED(result) ? result : E_INVALIDARG;
        }
        ComPtr<ID2D1ImageBrush> brush;
        const auto brush_properties = D2D1::BrushProperties(
            1.0f,
            D2D1::Matrix3x2F::Translation(bounds.left, bounds.top));
        result = d2d_context_->CreateImageBrush(
            image.Get(),
            D2D1::ImageBrushProperties(
                bounds, D2D1_EXTEND_MODE_CLAMP,
                D2D1_EXTEND_MODE_CLAMP,
                D2D1_INTERPOLATION_MODE_LINEAR),
            brush_properties,
            &brush);
        if (FAILED(result)) {
            return result;
        }
        const auto parameters = D2D1::LayerParameters1(
            D2D1::InfiniteRect(),
            nullptr,
            D2D1_ANTIALIAS_MODE_PER_PRIMITIVE,
            D2D1::Matrix3x2F::Identity(),
            1.0f,
            brush.Get(),
            D2D1_LAYER_OPTIONS1_NONE);
        d2d_context_->PushLayer(parameters, nullptr);
        ++layer_depth_;
        layer_brushes_.push_back(brush);
        return S_OK;
    }

    HRESULT pop_layer() noexcept {
        if (!drawing_ || layer_depth_ == 0) {
            return E_UNEXPECTED;
        }
        d2d_context_->PopLayer();
        --layer_depth_;
        if (!layer_brushes_.empty()) {
            layer_brushes_.pop_back();
        }
        return S_OK;
    }

    HRESULT begin_composite_group(
        std::uint32_t mode, float opacity, Path* clip = nullptr,
        bool mask_build = false, bool knockout = false,
        const D2D1_RECT_F* capture_bounds = nullptr,
        bool nonisolated = false) noexcept {
        // No implicit layer may cross a target switch. The scene validator
        // rejects these combinations before any page drawing starts.
        if (!drawing_ || layer_depth_ != 0 || axis_clip_depth_ != 0 ||
                !mask_captures_.empty() ||
                mode > 15 || !std::isfinite(opacity) || opacity < 0 || opacity > 1 ||
                (nonisolated && (mode != 0 || knockout || mask_build || clip != nullptr)) ||
                (clip != nullptr && (clip->owner != this || !clip->resource))) {
            return E_INVALIDARG;
        }
        CompositeCapture capture;
        ComPtr<ID2D1Image> current;
        d2d_context_->GetTarget(&current);
        auto result = current.As(&capture.previous);
        if (FAILED(result)) return result;
        auto size = capture.previous->GetPixelSize();
        d2d_context_->GetTransform(&capture.previous_transform);
        if ((mask_build && capture_bounds != nullptr) || clip != nullptr) {
            const auto& matrix = capture.previous_transform;
            const auto transform_point = [&](float x, float y) {
                return D2D1::Point2F(
                    x * matrix._11 + y * matrix._21 + matrix._31,
                    x * matrix._12 + y * matrix._22 + matrix._32);
            };
            D2D1_RECT_F device_bounds{};
            if (clip != nullptr) {
                result = clip->resource->GetBounds(&matrix, &device_bounds);
                if (FAILED(result)) return result;
            } else {
                const D2D1_POINT_2F corners[] = {
                    transform_point(capture_bounds->left, capture_bounds->top),
                    transform_point(capture_bounds->right, capture_bounds->top),
                    transform_point(capture_bounds->left, capture_bounds->bottom),
                    transform_point(capture_bounds->right, capture_bounds->bottom),
                };
                device_bounds = D2D1::RectF(
                    corners[0].x, corners[0].y, corners[0].x, corners[0].y);
                for (const auto& point : corners) {
                    device_bounds.left = (std::min)(device_bounds.left, point.x);
                    device_bounds.top = (std::min)(device_bounds.top, point.y);
                    device_bounds.right = (std::max)(device_bounds.right, point.x);
                    device_bounds.bottom = (std::max)(device_bounds.bottom, point.y);
                }
            }
            const auto left = device_bounds.left;
            const auto top = device_bounds.top;
            const auto right = device_bounds.right;
            const auto bottom = device_bounds.bottom;
            const auto dip_size = capture.previous->GetSize();
            if (dip_size.width <= 0 || dip_size.height <= 0) return E_INVALIDARG;
            if (!std::isfinite(left) || !std::isfinite(top) ||
                    !std::isfinite(right) || !std::isfinite(bottom)) {
                device_bounds = D2D1::RectF(
                    0, 0, dip_size.width, dip_size.height);
            }
            const auto scale_x = static_cast<float>(size.width) / dip_size.width;
            const auto scale_y = static_cast<float>(size.height) / dip_size.height;
            auto pixel_left = (std::max)(
                0, static_cast<int>(std::floor(device_bounds.left * scale_x)) - 1);
            auto pixel_top = (std::max)(
                0, static_cast<int>(std::floor(device_bounds.top * scale_y)) - 1);
            auto pixel_right = (std::min)(
                static_cast<int>(size.width),
                static_cast<int>(std::ceil(device_bounds.right * scale_x)) + 1);
            auto pixel_bottom = (std::min)(
                static_cast<int>(size.height),
                static_cast<int>(std::ceil(device_bounds.bottom * scale_y)) + 1);
            if (pixel_right <= pixel_left) {
                pixel_left = device_bounds.left >= dip_size.width
                    ? static_cast<int>(size.width) - 1 : 0;
                pixel_right = pixel_left + 1;
            }
            if (pixel_bottom <= pixel_top) {
                pixel_top = device_bounds.top >= dip_size.height
                    ? static_cast<int>(size.height) - 1 : 0;
                pixel_bottom = pixel_top + 1;
            }
            capture.source_origin = D2D1::Point2U(
                static_cast<UINT32>(pixel_left), static_cast<UINT32>(pixel_top));
            capture.destination_origin = D2D1::Point2F(
                static_cast<float>(pixel_left) / scale_x,
                static_cast<float>(pixel_top) / scale_y);
            size = D2D1::SizeU(
                static_cast<UINT32>(pixel_right - pixel_left),
                static_cast<UINT32>(pixel_bottom - pixel_top));
            capture.cropped = true;
        }
        // Source + temporary backdrop, plus a coverage mask for explicit clips.
        capture.bytes = static_cast<std::uint64_t>(size.width) * size.height * 4 *
            (mask_build ? 4 : (clip == nullptr ? 2 : 3));
        const auto budget = (std::max)(256ULL * 1024 * 1024, scene_cache_budget());
        if (capture.bytes == 0 || composite_bytes_ + capture.bytes > budget) {
            return E_OUTOFMEMORY;
        }
        const auto properties = D2D1::BitmapProperties1(
            D2D1_BITMAP_OPTIONS_TARGET,
            D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM,
                             D2D1_ALPHA_MODE_PREMULTIPLIED), dpi_, dpi_);
        result = d2d_context_->CreateBitmap(
            size, nullptr, 0, properties, &capture.source);
        if (FAILED(result)) return result;
        if (nonisolated) {
            result = d2d_context_->Flush();
            if (FAILED(result)) return result;
            d2d_context_->SetTarget(nullptr);
            result = capture.source->CopyFromBitmap(nullptr, capture.previous.Get(), nullptr);
            d2d_context_->SetTarget(capture.previous.Get());
            if (FAILED(result)) return result;
        }
        if (clip != nullptr) {
            result = d2d_context_->CreateBitmap(
                size, nullptr, 0, properties, &capture.mask);
            ComPtr<ID2D1SolidColorBrush> white;
            if (SUCCEEDED(result)) result = create_brush(0xffffffff, &white);
            if (SUCCEEDED(result)) result = d2d_context_->Flush();
            if (FAILED(result)) return result;
            // A clip is not an isolated transparency group: its children must
            // blend against the existing backdrop. Apply coverage only on exit.
            d2d_context_->SetTarget(nullptr);
            D2D1_POINT_2U destination{};
            const auto dimensions = capture.source->GetPixelSize();
            const auto source = D2D1::RectU(
                capture.source_origin.x, capture.source_origin.y,
                capture.source_origin.x + dimensions.width,
                capture.source_origin.y + dimensions.height);
            result = capture.source->CopyFromBitmap(
                &destination, capture.previous.Get(),
                capture.cropped ? &source : nullptr);
            if (SUCCEEDED(result)) {
                d2d_context_->SetTarget(capture.mask.Get());
                d2d_context_->Clear(D2D1::ColorF(0, 0, 0, 0));
                if (capture.cropped) {
                    auto adjusted = capture.previous_transform;
                    adjusted._31 -= capture.destination_origin.x;
                    adjusted._32 -= capture.destination_origin.y;
                    d2d_context_->SetTransform(adjusted);
                }
                // Use the same coverage rasterizer as ordinary clip layers.
                // Filled geometry realizations have different fractional-edge AA.
                const auto parameters = D2D1::LayerParameters1(
                    D2D1::InfiniteRect(), clip->resource.Get(),
                    D2D1_ANTIALIAS_MODE_PER_PRIMITIVE,
                    D2D1::Matrix3x2F::Identity(), 1.0f, nullptr,
                    D2D1_LAYER_OPTIONS1_NONE);
                d2d_context_->PushLayer(parameters, nullptr);
                D2D1_MATRIX_3X2_F clip_transform;
                d2d_context_->GetTransform(&clip_transform);
                d2d_context_->SetTransform(D2D1::Matrix3x2F::Identity());
                const auto dip_size = capture.mask->GetSize();
                d2d_context_->FillRectangle(
                    D2D1::RectF(0, 0, dip_size.width, dip_size.height), white.Get());
                d2d_context_->PopLayer();
                d2d_context_->SetTransform(clip_transform);
                result = d2d_context_->Flush();
            }
            d2d_context_->SetTarget(capture.previous.Get());
            d2d_context_->SetTransform(capture.previous_transform);
            if (FAILED(result)) return result;
        }
        capture.mode = mode;
        capture.opacity = opacity;
        capture.building_mask = mask_build;
        capture.knockout = knockout;
        capture.nonisolated = nonisolated;
        capture.previous_blend = d2d_context_->GetPrimitiveBlend();
        composite_bytes_ += capture.bytes;
        composite_captures_.push_back(capture);
        d2d_context_->SetTarget(capture.source.Get());
        if (capture.cropped) {
            auto adjusted = capture.previous_transform;
            adjusted._31 -= capture.destination_origin.x;
            adjusted._32 -= capture.destination_origin.y;
            d2d_context_->SetTransform(adjusted);
        }
        if (clip == nullptr && !nonisolated) d2d_context_->Clear(D2D1::ColorF(0, 0, 0, 0));
        // Offscreen captures have their own compositing state. Inheriting COPY
        // here makes nested bitmaps erase earlier content in the capture.
        // The parent's state is restored when this capture closes.
        d2d_context_->SetPrimitiveBlend(knockout
            ? D2D1_PRIMITIVE_BLEND_COPY : D2D1_PRIMITIVE_BLEND_SOURCE_OVER);
        return S_OK;
    }

    HRESULT set_luminosity_lut(
        const unsigned char* data, std::uint32_t size, std::uint32_t edge) noexcept {
        if (data == nullptr || edge < 2 || edge > 65 ||
                size != edge * edge * edge * 4) return E_INVALIDARG;
        ComPtr<ID2D1DeviceContext2> context;
        auto result = d2d_context_.As(&context);
        if (FAILED(result)) return result;
        const std::uint32_t extents[] = {edge, edge, edge};
        const std::uint32_t strides[] = {edge * 4, edge * edge * 4};
        ComPtr<ID2D1LookupTable3D> table;
        result = context->CreateLookupTable3D(D2D1_BUFFER_PRECISION_8BPC_UNORM,
            extents, data, size, strides, &table);
        if (SUCCEEDED(result)) luminosity_lut_ = table;
        return result;
    }

    HRESULT begin_composite_mask(
        float left, float top, float right, float bottom, bool luminosity,
        std::uint32_t background_argb) noexcept {
        if (!std::isfinite(left) || !std::isfinite(top) || !std::isfinite(right) ||
                !std::isfinite(bottom) || right <= left || bottom <= top) return E_INVALIDARG;
        const auto area = D2D1::RectF(left, top, right, bottom);
        auto result = begin_composite_group(
            0, 1.0f, nullptr, true, false, &area);
        if (FAILED(result)) return result;
        auto& capture = composite_captures_.back();
        capture.luminosity = luminosity;
        capture.mask_area = area;
        d2d_context_->GetTransform(&capture.mask_transform);
        if (luminosity || ((background_argb >> 24) & 0xff) != 0) {
            result = fill_rect(left, top, right, bottom, background_argb);
        }
        return result;
    }

    HRESULT end_composite_mask(
        const float* alpha_transfer = nullptr,
        std::uint32_t transfer_count = 0) noexcept {
        if (!drawing_ || composite_captures_.empty() || layer_depth_ != 0 ||
                !mask_captures_.empty() || !composite_captures_.back().building_mask) {
            return E_UNEXPECTED;
        }
        auto& capture = composite_captures_.back();
        const auto properties = D2D1::BitmapProperties1(
            D2D1_BITMAP_OPTIONS_TARGET, capture.source->GetPixelFormat(), dpi_, dpi_);
        ComPtr<ID2D1Bitmap1> coverage, content;
        auto result = d2d_context_->CreateBitmap(
            capture.source->GetPixelSize(), nullptr, 0, properties, &coverage);
        if (SUCCEEDED(result)) result = d2d_context_->CreateBitmap(
            capture.source->GetPixelSize(), nullptr, 0, properties, &content);
        ComPtr<ID2D1RectangleGeometry> area;
        if (SUCCEEDED(result)) result = d2d_factory_->CreateRectangleGeometry(
            capture.mask_area, &area);
        ComPtr<ID2D1Image> mask_image = capture.source;
        ComPtr<ID2D1Effect> luminance, color_conversion, transfer_effect;
        if (SUCCEEDED(result) && capture.luminosity) {
            if (!luminosity_lut_) return E_UNEXPECTED;
            result = d2d_context_->CreateEffect(CLSID_D2D1LookupTable3D, &color_conversion);
            if (SUCCEEDED(result)) {
                color_conversion->SetInput(0, capture.source.Get());
                result = color_conversion->SetValue(D2D1_LOOKUPTABLE3D_PROP_LUT,
                                                    luminosity_lut_.Get());
            }
            if (SUCCEEDED(result)) result = color_conversion->SetValue(
                D2D1_LOOKUPTABLE3D_PROP_ALPHA_MODE, D2D1_ALPHA_MODE_PREMULTIPLIED);
            if (SUCCEEDED(result)) result = d2d_context_->CreateEffect(
                CLSID_D2D1LuminanceToAlpha, &luminance);
            if (SUCCEEDED(result)) {
                luminance->SetInputEffect(0, color_conversion.Get());
                luminance->GetOutput(&mask_image);
            }
        }
        if (SUCCEEDED(result)) result = apply_alpha_transfer(
            mask_image.Get(), alpha_transfer, transfer_count,
            transfer_effect, mask_image);
        if (SUCCEEDED(result)) result = d2d_context_->Flush();
        if (FAILED(result)) return result;
        d2d_context_->SetTarget(nullptr);
        D2D1_POINT_2U destination{};
        const auto dimensions = capture.source->GetPixelSize();
        const auto source = D2D1::RectU(
            capture.source_origin.x, capture.source_origin.y,
            capture.source_origin.x + dimensions.width,
            capture.source_origin.y + dimensions.height);
        result = content->CopyFromBitmap(
            &destination, capture.previous.Get(), capture.cropped ? &source : nullptr);
        if (FAILED(result)) {
            d2d_context_->SetTarget(capture.source.Get());
            return result;
        }
        D2D1_MATRIX_3X2_F transform;
        d2d_context_->GetTransform(&transform);
        d2d_context_->SetTarget(coverage.Get());
        d2d_context_->Clear(D2D1::ColorF(0, 0, 0, 0));
        d2d_context_->SetTransform(capture.mask_transform);
        const auto parameters = D2D1::LayerParameters1(
            D2D1::InfiniteRect(), area.Get(), D2D1_ANTIALIAS_MODE_PER_PRIMITIVE,
            D2D1::Matrix3x2F::Identity(), 1.0f, nullptr, D2D1_LAYER_OPTIONS1_NONE);
        d2d_context_->PushLayer(parameters, nullptr);
        d2d_context_->SetTransform(D2D1::Matrix3x2F::Identity());
        d2d_context_->DrawImage(mask_image.Get(), D2D1::Point2F(0, 0),
            D2D1_INTERPOLATION_MODE_NEAREST_NEIGHBOR, D2D1_COMPOSITE_MODE_SOURCE_COPY);
        d2d_context_->PopLayer();
        result = d2d_context_->Flush();
        d2d_context_->SetTransform(transform);
        if (FAILED(result)) {
            d2d_context_->SetTarget(capture.source.Get());
            return result;
        }
        // Reuse the same stack entry for the applied mask scope. Children now
        // see the backdrop; clip-pop applies the finished coverage exactly once.
        capture.mask = coverage;
        capture.source = content;
        capture.building_mask = false;
        d2d_context_->SetTarget(content.Get());
        return S_OK;
    }

    HRESULT end_composite_group(bool clip = false) noexcept {
        if (!drawing_ || composite_captures_.empty() || layer_depth_ != 0 ||
                !mask_captures_.empty() ||
                composite_captures_.back().building_mask ||
                (composite_captures_.back().mask != nullptr) != clip) return E_UNEXPECTED;
        auto capture = composite_captures_.back();
        composite_captures_.pop_back();
        composite_bytes_ -= capture.bytes;
        auto result = d2d_context_->Flush();
        d2d_context_->SetPrimitiveBlend(capture.previous_blend);
        d2d_context_->SetTarget(capture.previous.Get());
        if (FAILED(result)) return result;
        d2d_context_->SetTransform(D2D1::Matrix3x2F::Identity());
        if (capture.mode == 0 && !clip && !capture.nonisolated) {
            d2d_context_->DrawBitmap(capture.source.Get(), nullptr,
                capture.opacity, D2D1_INTERPOLATION_MODE_NEAREST_NEIGHBOR);
        } else {
            ComPtr<ID2D1Bitmap1> backdrop;
            const auto properties = D2D1::BitmapProperties1(
                D2D1_BITMAP_OPTIONS_NONE,
                D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM,
                                 D2D1_ALPHA_MODE_PREMULTIPLIED), dpi_, dpi_);
            result = d2d_context_->CreateBitmap(
                capture.source->GetPixelSize(), nullptr, 0, properties, &backdrop);
            if (SUCCEEDED(result)) {
                d2d_context_->SetTarget(nullptr);
                D2D1_POINT_2U destination{};
                const auto dimensions = capture.source->GetPixelSize();
                const auto source = D2D1::RectU(
                    capture.source_origin.x, capture.source_origin.y,
                    capture.source_origin.x + dimensions.width,
                    capture.source_origin.y + dimensions.height);
                result = backdrop->CopyFromBitmap(
                    &destination, capture.previous.Get(),
                    capture.cropped ? &source : nullptr);
                d2d_context_->SetTarget(capture.previous.Get());
            }
            if (capture.nonisolated) {
                // Normal non-isolated group: its source already contains the
                // backdrop. Apply group opacity once to the premultiplied
                // difference, not source-over (which would count it twice).
                ComPtr<ID2D1Effect> interpolate;
                if (SUCCEEDED(result)) result = d2d_context_->CreateEffect(
                    CLSID_D2D1ArithmeticComposite, &interpolate);
                if (SUCCEEDED(result)) {
                    interpolate->SetInput(0, backdrop.Get());
                    interpolate->SetInput(1, capture.source.Get());
                    result = interpolate->SetValue(
                        D2D1_ARITHMETICCOMPOSITE_PROP_COEFFICIENTS,
                        D2D1::Vector4F(0, 1.0f - capture.opacity, capture.opacity, 0));
                }
                if (SUCCEEDED(result)) {
                    d2d_context_->DrawImage(interpolate.Get(), D2D1::Point2F(0, 0),
                        D2D1_INTERPOLATION_MODE_NEAREST_NEIGHBOR,
                        D2D1_COMPOSITE_MODE_SOURCE_COPY);
                    result = d2d_context_->Flush();
                }
                d2d_context_->SetTransform(capture.previous_transform);
                return result;
            }
            if (clip) {
                // premultiplied output = result * mask + backdrop * (1 - mask).
                // SOURCE_COPY preserves translucent alpha and untouched pixels.
                ComPtr<ID2D1Effect> inside, outside, combined;
                if (SUCCEEDED(result)) result = d2d_context_->CreateEffect(
                    CLSID_D2D1Composite, &inside);
                if (SUCCEEDED(result)) result = d2d_context_->CreateEffect(
                    CLSID_D2D1Composite, &outside);
                if (SUCCEEDED(result)) result = d2d_context_->CreateEffect(
                    CLSID_D2D1Composite, &combined);
                if (SUCCEEDED(result)) {
                    inside->SetInput(0, capture.mask.Get());
                    inside->SetInput(1, capture.source.Get());
                    result = inside->SetValue(D2D1_COMPOSITE_PROP_MODE,
                                              D2D1_COMPOSITE_MODE_SOURCE_IN);
                }
                if (SUCCEEDED(result)) {
                    outside->SetInput(0, backdrop.Get());
                    outside->SetInput(1, capture.mask.Get());
                    result = outside->SetValue(D2D1_COMPOSITE_PROP_MODE,
                                               D2D1_COMPOSITE_MODE_DESTINATION_OUT);
                }
                if (SUCCEEDED(result)) {
                    combined->SetInputEffect(0, outside.Get());
                    combined->SetInputEffect(1, inside.Get());
                    result = combined->SetValue(D2D1_COMPOSITE_PROP_MODE,
                                                D2D1_COMPOSITE_MODE_PLUS);
                }
                if (SUCCEEDED(result)) {
                    if (capture.cropped) {
                        const auto dip_size = capture.source->GetSize();
                        d2d_context_->PushAxisAlignedClip(
                            D2D1::RectF(
                                capture.destination_origin.x,
                                capture.destination_origin.y,
                                capture.destination_origin.x + dip_size.width,
                                capture.destination_origin.y + dip_size.height),
                            D2D1_ANTIALIAS_MODE_ALIASED);
                    }
                    d2d_context_->DrawImage(
                        combined.Get(), capture.destination_origin,
                        D2D1_INTERPOLATION_MODE_NEAREST_NEIGHBOR,
                        D2D1_COMPOSITE_MODE_SOURCE_COPY);
                    if (capture.cropped) {
                        d2d_context_->PopAxisAlignedClip();
                    }
                    result = d2d_context_->Flush();
                }
                d2d_context_->SetTransform(capture.previous_transform);
                return result;
            }
            ComPtr<ID2D1Effect> alpha;
            ComPtr<ID2D1Effect> blend;
            if (SUCCEEDED(result)) result = d2d_context_->CreateEffect(CLSID_D2D1ColorMatrix, &alpha);
            if (SUCCEEDED(result)) {
                alpha->SetInput(0, capture.source.Get());
                const auto matrix = D2D1::Matrix5x4F(
                    1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,capture.opacity, 0,0,0,0);
                result = alpha->SetValue(D2D1_COLORMATRIX_PROP_COLOR_MATRIX, matrix);
            }
            if (SUCCEEDED(result)) result = d2d_context_->CreateEffect(CLSID_D2D1Blend, &blend);
            if (SUCCEEDED(result)) {
                constexpr D2D1_BLEND_MODE modes[] = {
                    D2D1_BLEND_MODE_MULTIPLY, // mode zero is handled above
                    D2D1_BLEND_MODE_MULTIPLY, D2D1_BLEND_MODE_SCREEN,
                    D2D1_BLEND_MODE_OVERLAY, D2D1_BLEND_MODE_DARKEN,
                    D2D1_BLEND_MODE_LIGHTEN, D2D1_BLEND_MODE_COLOR_DODGE,
                    D2D1_BLEND_MODE_COLOR_BURN, D2D1_BLEND_MODE_HARD_LIGHT,
                    D2D1_BLEND_MODE_SOFT_LIGHT, D2D1_BLEND_MODE_DIFFERENCE,
                    D2D1_BLEND_MODE_EXCLUSION, D2D1_BLEND_MODE_HUE,
                    D2D1_BLEND_MODE_SATURATION, D2D1_BLEND_MODE_COLOR,
                    D2D1_BLEND_MODE_LUMINOSITY};
                blend->SetInput(0, backdrop.Get());
                blend->SetInputEffect(1, alpha.Get());
                result = blend->SetValue(D2D1_BLEND_PROP_MODE, modes[capture.mode]);
                if (SUCCEEDED(result)) {
                    d2d_context_->DrawImage(blend.Get(), D2D1::Point2F(0, 0),
                        D2D1_INTERPOLATION_MODE_NEAREST_NEIGHBOR,
                        D2D1_COMPOSITE_MODE_SOURCE_COPY);
                    // Complete the effect before releasing its input snapshots.
                    result = d2d_context_->Flush();
                }
            }
        }
        d2d_context_->SetTransform(capture.previous_transform);
        return result;
    }

    HRESULT read_pixels(void* pixels, std::size_t size) noexcept {
        // Explicit diagnostic readback only; never called by the display loop.
        if (!drawing_ || pixels == nullptr || layer_depth_ != 0 ||
                !mask_captures_.empty()) return E_INVALIDARG;
        ComPtr<ID2D1Image> current;
        d2d_context_->GetTarget(&current);
        ComPtr<ID2D1Bitmap1> source;
        auto result = current.As(&source);
        if (FAILED(result)) return result;
        const auto dimensions = source->GetPixelSize();
        const auto stride = static_cast<std::size_t>(dimensions.width) * 4;
        if (size < stride * dimensions.height) return E_INVALIDARG;
        ComPtr<ID2D1Bitmap1> readable;
        const auto properties = D2D1::BitmapProperties1(
            D2D1_BITMAP_OPTIONS_CPU_READ | D2D1_BITMAP_OPTIONS_CANNOT_DRAW,
            source->GetPixelFormat(), dpi_, dpi_);
        result = d2d_context_->CreateBitmap(dimensions, nullptr, 0, properties, &readable);
        if (FAILED(result)) return result;
        result = d2d_context_->Flush();
        if (FAILED(result)) return result;
        d2d_context_->SetTarget(nullptr);
        result = readable->CopyFromBitmap(nullptr, source.Get(), nullptr);
        d2d_context_->SetTarget(source.Get());
        if (FAILED(result)) return result;
        D2D1_MAPPED_RECT mapped{};
        result = readable->Map(D2D1_MAP_OPTIONS_READ, &mapped);
        if (FAILED(result)) return result;
        for (std::uint32_t row = 0; row < dimensions.height; ++row) {
            std::memcpy(static_cast<unsigned char*>(pixels) + row * stride,
                        mapped.bits + row * mapped.pitch, stride);
        }
        return readable->Unmap();
    }

    HRESULT fill_rect(
        float left,
        float top,
        float right,
        float bottom,
        std::uint32_t argb) noexcept {
        if (!drawing_ || right <= left || bottom <= top) {
            return E_INVALIDARG;
        }
        ComPtr<ID2D1SolidColorBrush> brush;
        auto result = create_brush(argb, &brush);
        if (FAILED(result)) {
            return result;
        }
        d2d_context_->FillRectangle(D2D1::RectF(left, top, right, bottom), brush.Get());
        return S_OK;
    }

    HRESULT stroke_rect(
        float left,
        float top,
        float right,
        float bottom,
        std::uint32_t argb,
        float width) noexcept {
        if (!drawing_ || right <= left || bottom <= top || width <= 0.0f) {
            return E_INVALIDARG;
        }
        ComPtr<ID2D1SolidColorBrush> brush;
        auto result = create_brush(argb, &brush);
        if (FAILED(result)) {
            return result;
        }
        d2d_context_->DrawRectangle(
            D2D1::RectF(left, top, right, bottom), brush.Get(), width);
        return S_OK;
    }

    HRESULT fill_path(Path* path, std::uint32_t argb) noexcept {
        if (!drawing_ || path == nullptr || path->owner != this || !path->resource) {
            return E_INVALIDARG;
        }
        ComPtr<ID2D1SolidColorBrush> brush;
        auto result = create_brush(argb, &brush);
        if (FAILED(result)) {
            return result;
        }
        if (d2d_context1_ && path->fill_realization) {
            d2d_context1_->DrawGeometryRealization(
                path->fill_realization.Get(), brush.Get());
        } else {
            d2d_context_->FillGeometry(path->resource.Get(), brush.Get());
        }
        return S_OK;
    }

    HRESULT stroke_path(
        Path* path,
        std::uint32_t argb,
        float width,
        StrokeStyle* stroke_style = nullptr) noexcept {
        if (!drawing_ || path == nullptr || path->owner != this ||
                !path->resource || width < 0.0f ||
                (stroke_style != nullptr &&
                 (stroke_style->owner != this || !stroke_style->resource))) {
            return E_INVALIDARG;
        }
        ComPtr<ID2D1SolidColorBrush> brush;
        auto result = create_brush(argb, &brush);
        if (FAILED(result)) {
            return result;
        }
        d2d_context_->DrawGeometry(
            path->resource.Get(), brush.Get(), width,
            stroke_style == nullptr ? nullptr : stroke_style->resource.Get());
        return S_OK;
    }

    HRESULT fill_linear_gradient(
        Path* path,
        float start_x,
        float start_y,
        float end_x,
        float end_y,
        const SpdfD2DGradientStop* stops,
        std::uint32_t stop_count) noexcept {
        ComPtr<ID2D1LinearGradientBrush> brush;
        auto result = create_linear_gradient_brush(
            start_x, start_y, end_x, end_y, stops, stop_count, &brush);
        if (FAILED(result)) return result;
        return fill_gradient_path(path, brush.Get());
    }

    HRESULT create_linear_gradient_brush(
        float start_x,
        float start_y,
        float end_x,
        float end_y,
        const SpdfD2DGradientStop* stops,
        std::uint32_t stop_count,
        ID2D1LinearGradientBrush** brush) noexcept {
        if (!d2d_context_ || brush == nullptr || !std::isfinite(start_x) ||
                !std::isfinite(start_y) || !std::isfinite(end_x) ||
                !std::isfinite(end_y)) {
            return E_INVALIDARG;
        }
        *brush = nullptr;
        ComPtr<ID2D1GradientStopCollection> collection;
        auto result = create_gradient_stop_collection(
            stops, stop_count, &collection);
        if (FAILED(result)) {
            return result;
        }
        return d2d_context_->CreateLinearGradientBrush(
            D2D1::LinearGradientBrushProperties(
                D2D1::Point2F(start_x, start_y),
                D2D1::Point2F(end_x, end_y)),
            collection.Get(),
            brush);
    }

    HRESULT fill_radial_gradient(
        Path* path,
        float center_x,
        float center_y,
        float origin_x,
        float origin_y,
        float radius_x,
        float radius_y,
        const SpdfD2DGradientStop* stops,
        std::uint32_t stop_count) noexcept {
        ComPtr<ID2D1RadialGradientBrush> brush;
        auto result = create_radial_gradient_brush(
            center_x, center_y, origin_x, origin_y, radius_x, radius_y,
            stops, stop_count, &brush);
        if (FAILED(result)) return result;
        return fill_gradient_path(path, brush.Get());
    }

    HRESULT create_radial_gradient_brush(
        float center_x,
        float center_y,
        float origin_x,
        float origin_y,
        float radius_x,
        float radius_y,
        const SpdfD2DGradientStop* stops,
        std::uint32_t stop_count,
        ID2D1RadialGradientBrush** brush) noexcept {
        if (!d2d_context_ || brush == nullptr || !std::isfinite(center_x) ||
                !std::isfinite(center_y) || !std::isfinite(origin_x) ||
                !std::isfinite(origin_y) || !std::isfinite(radius_x) ||
                !std::isfinite(radius_y) || radius_x <= 0.0f ||
                radius_y <= 0.0f) {
            return E_INVALIDARG;
        }
        *brush = nullptr;
        ComPtr<ID2D1GradientStopCollection> collection;
        auto result = create_gradient_stop_collection(
            stops, stop_count, &collection);
        if (FAILED(result)) {
            return result;
        }
        return d2d_context_->CreateRadialGradientBrush(
            D2D1::RadialGradientBrushProperties(
                D2D1::Point2F(center_x, center_y),
                D2D1::Point2F(origin_x - center_x, origin_y - center_y),
                radius_x,
                radius_y),
            collection.Get(),
            brush);
    }

    HRESULT fill_gradient_path(Path* path, ID2D1Brush* brush) noexcept {
        if (!drawing_ || path == nullptr || path->owner != this ||
                !path->resource || brush == nullptr) {
            return E_INVALIDARG;
        }
        d2d_context_->FillGeometry(path->resource.Get(), brush);
        return S_OK;
    }

    HRESULT draw_bitmap(
        Bitmap* bitmap,
        float left,
        float top,
        float right,
        float bottom,
        float opacity, bool interpolate) noexcept {
        if (!drawing_ || bitmap == nullptr || bitmap->owner != this ||
                !bitmap->resource || right <= left || bottom <= top) {
            return E_INVALIDARG;
        }
        const auto destination = D2D1::RectF(left, top, right, bottom);
        d2d_context_->DrawBitmap(
            bitmap->resource.Get(),
            &destination,
            std::clamp(opacity, 0.0f, 1.0f),
            interpolate ? D2D1_INTERPOLATION_MODE_LINEAR : D2D1_INTERPOLATION_MODE_NEAREST_NEIGHBOR,
            nullptr);
        return S_OK;
    }

    HRESULT end_frame() noexcept {
        if (!d2d_context_ || !swap_chain_ || !drawing_) {
            return E_UNEXPECTED;
        }
        if (!composite_captures_.empty()) {
            while (layer_depth_ != 0) {
                d2d_context_->PopLayer();
                --layer_depth_;
            }
            layer_brushes_.clear();
            mask_captures_.clear();
            d2d_context_->SetTarget(target_.Get());
            composite_captures_.clear();
            composite_bytes_ = 0;
            drawing_ = false;
            d2d_context_->EndDraw();
            return E_UNEXPECTED;
        }
        if (!mask_captures_.empty()) {
            d2d_context_->SetTarget(
                mask_captures_.front().previous_target.Get());
            mask_captures_.clear();
            drawing_ = false;
            d2d_context_->EndDraw();
            return E_UNEXPECTED;
        }
        if (axis_clip_depth_ != 0) {
            while (axis_clip_depth_ != 0) {
                d2d_context_->PopAxisAlignedClip();
                --axis_clip_depth_;
            }
            drawing_ = false;
            d2d_context_->EndDraw();
            return E_UNEXPECTED;
        }
        if (layer_depth_ != 0) {
            while (layer_depth_ != 0) {
                d2d_context_->PopLayer();
                --layer_depth_;
            }
            layer_brushes_.clear();
            drawing_ = false;
            d2d_context_->EndDraw();
            return E_UNEXPECTED;
        }
        drawing_ = false;
        auto result = d2d_context_->EndDraw();
        if (result == D2DERR_RECREATE_TARGET) {
            d2d_context_->SetTarget(nullptr);
            target_.Reset();
            result = create_target();
            if (FAILED(result)) {
                return result;
            }
            return S_FALSE;
        }
        if (FAILED(result)) {
            return result;
        }
        return swap_chain_->Present(1, 0);
    }

    HRESULT begin_scene_recording(
        ID2D1Image** previous_target,
        ID2D1CommandList** commands) noexcept {
        if (!drawing_ || previous_target == nullptr || commands == nullptr ||
                !mask_captures_.empty() || !composite_captures_.empty() ||
                layer_depth_ != 0 || axis_clip_depth_ != 0) {
            return E_UNEXPECTED;
        }
        *previous_target = nullptr;
        *commands = nullptr;
        d2d_context_->GetTarget(previous_target);
        ComPtr<ID2D1CommandList> created;
        const auto result = d2d_context_->CreateCommandList(&created);
        if (FAILED(result)) return result;
        d2d_context_->SetTarget(created.Get());
        created.CopyTo(commands);
        return S_OK;
    }

    HRESULT end_scene_recording(
        ID2D1Image* previous_target,
        ID2D1CommandList* commands) noexcept {
        if (previous_target == nullptr || commands == nullptr) return E_INVALIDARG;
        d2d_context_->SetTarget(previous_target);
        return commands->Close();
    }

    HRESULT draw_command_list(
        ID2D1CommandList* commands,
        const SpdfD2DTransform& transform) noexcept {
        if (!drawing_ || commands == nullptr) return E_INVALIDARG;
        const auto result = set_transform(
            transform.m11, transform.m12, transform.m21, transform.m22,
            transform.dx, transform.dy);
        if (FAILED(result)) return result;
        d2d_context_->DrawImage(commands);
        return S_OK;
    }

    HRESULT draw_cached_scene(Scene* scene, const SpdfD2DTransform& transform) noexcept;
    HRESULT draw_scene_preview(Scene* scene, const SpdfD2DTransform& transform) noexcept;

private:
    std::uint64_t scene_cache_budget() noexcept {
        const auto now = GetTickCount64();
        if (budget_sampled_ && now - budget_sampled_ < 1000) return raster_budget_;
        budget_sampled_ = now;
        constexpr std::uint64_t mib = 1024 * 1024;
        std::uint64_t budget = 128 * mib;
        MEMORYSTATUSEX memory{};
        memory.dwLength = sizeof(memory);
        if (GlobalMemoryStatusEx(&memory)) {
            budget = (std::min)({1024 * mib, memory.ullTotalPhys / 32,
                                memory.ullAvailPhys / 8});
        }
        ComPtr<IDXGIAdapter> adapter;
        ComPtr<IDXGIAdapter3> adapter3;
        DXGI_QUERY_VIDEO_MEMORY_INFO video{};
        if (SUCCEEDED(dxgi_device_->GetAdapter(&adapter)) &&
                SUCCEEDED(adapter.As(&adapter3)) &&
                SUCCEEDED(adapter3->QueryVideoMemoryInfo(
                    0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &video))) {
            std::uint64_t owned = 0;
            for (const auto& entry : scene_rasters_) owned += entry.bytes;
            const auto others = video.CurrentUsage > owned ? video.CurrentUsage - owned : 0;
            const auto room = video.Budget > others ? video.Budget - others : 0;
            budget = (std::min)({budget, video.Budget / 8, room / 4});
        }
        raster_budget_ = budget;
        return budget;
    }
    std::uint64_t budget_sampled_ = 0;
    std::uint64_t raster_budget_ = 128ULL * 1024 * 1024;
    struct SceneRaster {
        std::shared_ptr<char> identity;
        ComPtr<ID2D1Bitmap1> bitmap;
        SpdfD2DTransform transform{};
        float dpi = 96.0f;
        std::uint64_t bytes = 0;
        std::uint64_t used = 0;
    };
    std::vector<SceneRaster> scene_rasters_;
    std::uint64_t raster_clock_ = 0;
    struct CompositeCapture {
        ComPtr<ID2D1Bitmap1> previous;
        ComPtr<ID2D1Bitmap1> source;
        ComPtr<ID2D1Bitmap1> mask;
        bool building_mask = false;
        bool luminosity = false;
        D2D1_RECT_F mask_area{};
        D2D1_MATRIX_3X2_F mask_transform{};
        D2D1_MATRIX_3X2_F previous_transform{};
        D2D1_POINT_2U source_origin{};
        D2D1_POINT_2F destination_origin{};
        std::uint32_t mode = 0;
        float opacity = 1.0f;
        bool knockout = false;
        bool nonisolated = false;
        bool cropped = false;
        D2D1_PRIMITIVE_BLEND previous_blend = D2D1_PRIMITIVE_BLEND_SOURCE_OVER;
        std::uint64_t bytes = 0;
    };
    struct MaskCapture {
        ComPtr<ID2D1Image> previous_target;
        ComPtr<ID2D1CommandList> commands;
        std::uint32_t layer_depth = 0;
        bool luminosity = false;
    };

    void realize_path(Path* path) noexcept {
        if (d2d_context1_ && path != nullptr && path->resource) {
            // 0.05 PDF points stays below half a pixel at the 800% UI limit.
            d2d_context1_->CreateFilledGeometryRealization(
                path->resource.Get(), 0.05f, &path->fill_realization);
        }
    }

    HRESULT create_brush(
        std::uint32_t argb,
        ID2D1SolidColorBrush** brush) noexcept {
        const auto cached = brushes_.find(argb);
        if (cached != brushes_.end()) {
            return cached->second.CopyTo(brush);
        }
        const auto alpha = static_cast<float>((argb >> 24) & 0xff) / 255.0f;
        const auto red = static_cast<float>((argb >> 16) & 0xff) / 255.0f;
        const auto green = static_cast<float>((argb >> 8) & 0xff) / 255.0f;
        const auto blue = static_cast<float>(argb & 0xff) / 255.0f;
        ComPtr<ID2D1SolidColorBrush> created;
        const auto result = d2d_context_->CreateSolidColorBrush(
            D2D1::ColorF(red, green, blue, alpha), &created);
        if (FAILED(result)) {
            return result;
        }
        brushes_.emplace(argb, created);
        return created.CopyTo(brush);
    }

    HRESULT create_gradient_stop_collection(
        const SpdfD2DGradientStop* stops,
        std::uint32_t stop_count,
        ID2D1GradientStopCollection** collection) noexcept {
        if (stops == nullptr || collection == nullptr || stop_count < 2 ||
                stop_count > 256) {
            return E_INVALIDARG;
        }
        std::vector<D2D1_GRADIENT_STOP> native_stops;
        native_stops.reserve(stop_count);
        float previous = -1.0f;
        for (std::uint32_t index = 0; index < stop_count; ++index) {
            const auto position = stops[index].position;
            if (!std::isfinite(position) || position < 0.0f ||
                    position > 1.0f || position < previous) {
                return E_INVALIDARG;
            }
            previous = position;
            const auto argb = stops[index].argb;
            const auto alpha = static_cast<float>((argb >> 24) & 0xff) / 255.0f;
            const auto red = static_cast<float>((argb >> 16) & 0xff) / 255.0f;
            const auto green = static_cast<float>((argb >> 8) & 0xff) / 255.0f;
            const auto blue = static_cast<float>(argb & 0xff) / 255.0f;
            native_stops.push_back(D2D1::GradientStop(
                position, D2D1::ColorF(red, green, blue, alpha)));
        }
        return d2d_context_->CreateGradientStopCollection(
            native_stops.data(),
            static_cast<UINT32>(native_stops.size()),
            D2D1_GAMMA_2_2,
            D2D1_EXTEND_MODE_CLAMP,
            collection);
    }

    HRESULT create_target() noexcept {
        ComPtr<IDXGISurface> back_buffer;
        auto result = swap_chain_->GetBuffer(0, IID_PPV_ARGS(&back_buffer));
        if (FAILED(result)) {
            return result;
        }
        const auto properties = D2D1::BitmapProperties1(
            D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW,
            D2D1::PixelFormat(
                DXGI_FORMAT_B8G8R8A8_UNORM,
                D2D1_ALPHA_MODE_PREMULTIPLIED),
            dpi_,
            dpi_);
        result = d2d_context_->CreateBitmapFromDxgiSurface(
            back_buffer.Get(), &properties, &target_);
        if (SUCCEEDED(result)) {
            d2d_context_->SetTarget(target_.Get());
            d2d_context_->SetDpi(dpi_, dpi_);
            configure_antialiasing();
        }
        return result;
    }

    void configure_antialiasing() noexcept {
        if (!d2d_context_) {
            return;
        }
        d2d_context_->SetAntialiasMode(D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
        d2d_context_->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
    }

    SpdfD2DDriver driver_ = SPDF_D2D_DRIVER_NONE;
    D3D_FEATURE_LEVEL feature_level_ = D3D_FEATURE_LEVEL_10_0;
    float dpi_ = 96.0f;
    ComPtr<ID3D11Device> d3d_device_;
    ComPtr<IDXGIDevice> dxgi_device_;
    ComPtr<IDXGIFactory2> dxgi_factory_;
    ComPtr<IDXGISwapChain1> swap_chain_;
    ComPtr<ID2D1Factory1> d2d_factory_;
    ComPtr<ID2D1Device> d2d_device_;
    ComPtr<ID2D1DeviceContext> d2d_context_;
    ComPtr<ID2D1DeviceContext1> d2d_context1_;
    ComPtr<ID2D1Bitmap1> target_;
    ComPtr<IDWriteFactory> dwrite_factory_;
    std::unordered_map<std::uint32_t, ComPtr<ID2D1SolidColorBrush>> brushes_;
    std::vector<ComPtr<ID2D1Brush>> layer_brushes_;
    std::vector<MaskCapture> mask_captures_;
    std::vector<CompositeCapture> composite_captures_;
    std::uint64_t composite_bytes_ = 0;
    ComPtr<ID2D1LookupTable3D> luminosity_lut_;
    std::uint32_t layer_depth_ = 0;
    std::uint32_t axis_clip_depth_ = 0;
    bool drawing_ = false;
};

struct SceneCommand {
    SpdfD2DSceneCommand command{};
    std::unique_ptr<Surface::Bitmap> bitmap;
    std::unique_ptr<Surface::Path> path;
    std::unique_ptr<Surface::StrokeStyle> stroke_style;
    std::vector<SpdfD2DGradientStop> stops;
    std::vector<float> transfer;
    ComPtr<ID2D1LinearGradientBrush> linear_brush;
    ComPtr<ID2D1RadialGradientBrush> radial_brush;
};

struct Scene {
    Surface* owner = nullptr;
    std::shared_ptr<char> identity = std::make_shared<char>();
    std::vector<SceneCommand> commands;
    ComPtr<ID2D1CommandList> display_list;
    bool recordable = true;
};

D2D1_MATRIX_3X2_F compose_transform(
    const SpdfD2DTransform& page,
    const SpdfD2DTransform& item) noexcept {
    return D2D1::Matrix3x2F(
        page.m11 * item.m11 + page.m21 * item.m12,
        page.m12 * item.m11 + page.m22 * item.m12,
        page.m11 * item.m21 + page.m21 * item.m22,
        page.m12 * item.m21 + page.m22 * item.m22,
        page.m11 * item.dx + page.m21 * item.dy + page.dx,
        page.m12 * item.dx + page.m22 * item.dy + page.dy);
}

HRESULT replay_scene(
    Surface* surface,
    Scene* scene,
    const SpdfD2DTransform& page) noexcept {
    if (surface == nullptr || scene == nullptr || scene->owner != surface) {
        return E_INVALIDARG;
    }
    const auto set_item_transform = [&](const SpdfD2DSceneCommand& command) {
        const auto matrix = (command.flags & SPDF_D2D_SCENE_HAS_TRANSFORM) != 0
            ? compose_transform(page, command.transform)
            : D2D1::Matrix3x2F(
                page.m11, page.m12, page.m21, page.m22, page.dx, page.dy);
        return surface->set_transform(
            matrix._11, matrix._12, matrix._21, matrix._22, matrix._31, matrix._32);
    };
    for (const auto& stored : scene->commands) {
        const auto& command = stored.command;
        HRESULT result = S_OK;
        switch (command.type) {
        case SPDF_D2D_SCENE_FILL_RECT:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) result = surface->fill_rect(
                command.values[0], command.values[1], command.values[2], command.values[3],
                command.uint_values[0]);
            break;
        case SPDF_D2D_SCENE_CLIP_PUSH:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) result = surface->push_clip_path(
                static_cast<Surface::Path*>(command.resource));
            break;
        case SPDF_D2D_SCENE_CLIP_POP:
            result = surface->pop_clip();
            break;
        case SPDF_D2D_SCENE_RECT_CLIP_PUSH:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) result = surface->push_axis_aligned_clip(
                command.values[0], command.values[1],
                command.values[2], command.values[3]);
            break;
        case SPDF_D2D_SCENE_RECT_CLIP_POP:
            result = surface->pop_axis_aligned_clip();
            break;
        case SPDF_D2D_SCENE_OPACITY_PUSH:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) result = surface->push_opacity_layer(command.values[0]);
            break;
        case SPDF_D2D_SCENE_LAYER_POP:
            result = surface->pop_layer();
            break;
        case SPDF_D2D_SCENE_COMPOSITE_PUSH:
            if ((command.uint_values[1] & ~3U) != 0) {
                result = E_INVALIDARG;
                break;
            }
            result = surface->begin_composite_group(
                command.uint_values[0], command.values[0], nullptr, false,
                (command.uint_values[1] & 1) != 0, nullptr,
                (command.uint_values[1] & 2) != 0);
            break;
        case SPDF_D2D_SCENE_COMPOSITE_POP:
            result = surface->end_composite_group();
            break;
        case SPDF_D2D_SCENE_CLIP_GROUP_PUSH:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) result = surface->begin_composite_group(
                0, 1.0f, static_cast<Surface::Path*>(command.resource));
            break;
        case SPDF_D2D_SCENE_CLIP_GROUP_POP:
            result = surface->end_composite_group(true);
            break;
        case SPDF_D2D_SCENE_MASK_BEGIN:
        case SPDF_D2D_SCENE_COMPOSITE_MASK_BEGIN:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) {
                if (command.type == SPDF_D2D_SCENE_MASK_BEGIN) {
                    result = surface->begin_mask(
                        command.values[0], command.values[1], command.values[2], command.values[3],
                        command.uint_values[0] != 0, command.uint_values[1]);
                } else {
                    result = surface->begin_composite_mask(
                        command.values[0], command.values[1], command.values[2], command.values[3],
                        command.uint_values[0] != 0, command.uint_values[1]);
                }
            }
            break;
        case SPDF_D2D_SCENE_MASK_END:
        case SPDF_D2D_SCENE_COMPOSITE_MASK_END:
            result = surface->set_transform(1, 0, 0, 1, 0, 0);
            if (SUCCEEDED(result)) {
                const auto* values = stored.transfer.empty() ? nullptr : stored.transfer.data();
                const auto count = static_cast<std::uint32_t>(stored.transfer.size());
                result = command.type == SPDF_D2D_SCENE_MASK_END
                    ? surface->end_mask(values, count)
                    : surface->end_composite_mask(values, count);
            }
            break;
        case SPDF_D2D_SCENE_BITMAP:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) result = surface->draw_bitmap(
                static_cast<Surface::Bitmap*>(command.resource),
                command.values[0], command.values[1], command.values[2], command.values[3],
                command.values[4], command.uint_values[0] != 0);
            break;
        case SPDF_D2D_SCENE_PATH_FILL:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) result = surface->fill_path(
                static_cast<Surface::Path*>(command.resource), command.uint_values[0]);
            break;
        case SPDF_D2D_SCENE_PATH_STROKE:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) result = surface->stroke_path(
                static_cast<Surface::Path*>(command.resource), command.uint_values[0],
                command.values[0], static_cast<Surface::StrokeStyle*>(command.stroke_style));
            break;
        case SPDF_D2D_SCENE_LINEAR_GRADIENT:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) result = surface->fill_gradient_path(
                static_cast<Surface::Path*>(command.resource), stored.linear_brush.Get());
            break;
        case SPDF_D2D_SCENE_RADIAL_GRADIENT:
            result = set_item_transform(command);
            if (SUCCEEDED(result)) result = surface->fill_gradient_path(
                static_cast<Surface::Path*>(command.resource), stored.radial_brush.Get());
            break;
        default:
            return E_INVALIDARG;
        }
        if (FAILED(result)) return result;
    }
    return surface->set_transform(page.m11, page.m12, page.m21, page.m22, page.dx, page.dy);
}

// Animated zoom can temporarily rescale an existing complex-page raster.
HRESULT Surface::draw_scene_preview(Scene* scene, const SpdfD2DTransform& t) noexcept {
    if (scene->recordable || t.m12 != 0 || t.m21 != 0 ||
            t.m11 <= 0 || t.m22 <= 0 || !std::isfinite(t.m11) ||
            !std::isfinite(t.m22) || !std::isfinite(t.dx) || !std::isfinite(t.dy) ||
            layer_depth_ || axis_clip_depth_ || !composite_captures_.empty() ||
            !mask_captures_.empty()) return S_FALSE;
    SceneRaster* best = nullptr;
    for (auto& cached : scene_rasters_) {
        if (cached.identity == scene->identity && cached.dpi == dpi_ &&
                (!best || cached.used > best->used)) best = &cached;
    }
    if (!best) return S_FALSE;
    const float sx = t.m11 / best->transform.m11;
    const float sy = t.m22 / best->transform.m22;
    if (!std::isfinite(sx) || !std::isfinite(sy)) return S_FALSE;
    // Scale the cached page origin as well as its pixels, preserving the
    // cursor anchor even when the raster has a fractional-pixel border.
    d2d_context_->SetTransform(D2D1::Matrix3x2F(sx, 0, 0, sy,
        t.dx - best->transform.dx * sx, t.dy - best->transform.dy * sy));
    d2d_context_->DrawBitmap(best->bitmap.Get(), nullptr, 1.0f,
        D2D1_INTERPOLATION_MODE_LINEAR);
    best->used = ++raster_clock_;
    return set_transform(t.m11, t.m12, t.m21, t.m22, t.dx, t.dy);
}

// Complex pages cannot use a command list because their blend operations read
// the backdrop. Cache their GPU-rendered pixels at the exact scale instead.
// Integer-pixel translations preserve coverage; other transforms replay normally.
HRESULT Surface::draw_cached_scene(Scene* scene, const SpdfD2DTransform& t) noexcept {
    const auto budget = scene_cache_budget();
    scene_rasters_.erase(std::remove_if(scene_rasters_.begin(), scene_rasters_.end(),
        [](const SceneRaster& entry) { return entry.identity.use_count() == 1; }), scene_rasters_.end());
    std::uint64_t used = 0;
    for (const auto& entry : scene_rasters_) used += entry.bytes;
    while (used > budget && !scene_rasters_.empty()) {
        auto oldest = std::min_element(scene_rasters_.begin(), scene_rasters_.end(),
            [](const SceneRaster& a, const SceneRaster& b) { return a.used < b.used; });
        used -= oldest->bytes;
        scene_rasters_.erase(oldest);
    }
    if (scene->commands.size() < 256 || t.m12 != 0 || t.m21 != 0 ||
            t.m11 <= 0 || t.m22 <= 0 || !std::isfinite(t.dx) || !std::isfinite(t.dy) ||
            !std::isfinite(t.m11) || !std::isfinite(t.m22) ||
            layer_depth_ || axis_clip_depth_ || !composite_captures_.empty() ||
            !mask_captures_.empty()) return replay_scene(this, scene, t);
    const auto& first = scene->commands.front().command;
    if (first.type != SPDF_D2D_SCENE_FILL_RECT || first.flags != 0 ||
            first.uint_values[0] != 0xffffffff || first.values[0] != 0 ||
            first.values[1] != 0) return replay_scene(this, scene, t);
    const float ratio = dpi_ / 96.0f;
    for (auto& cached : scene_rasters_) {
        const float x = (t.dx - cached.transform.dx) * ratio;
        const float y = (t.dy - cached.transform.dy) * ratio;
        if (cached.identity == scene->identity && cached.dpi == dpi_ &&
                cached.transform.m11 == t.m11 && cached.transform.m22 == t.m22 &&
                std::abs(x - std::round(x)) < 0.0001f &&
                std::abs(y - std::round(y)) < 0.0001f) {
            cached.used = ++raster_clock_;
            d2d_context_->SetTransform(D2D1::Matrix3x2F::Translation(
                t.dx - cached.transform.dx,
                t.dy - cached.transform.dy));
            d2d_context_->DrawBitmap(cached.bitmap.Get(), nullptr, 1.0f,
                D2D1_INTERPOLATION_MODE_NEAREST_NEIGHBOR);
            return set_transform(t.m11, t.m12, t.m21, t.m22, t.dx, t.dy);
        }
    }
    // Two pixels protect antialiased page edges. Align to the original pixel
    // phase so cached and direct output have identical sample positions.
    const float border = std::ceil(2 * ratio);
    const float origin_x = (std::floor(t.dx * ratio) - border) / ratio;
    const float origin_y = (std::floor(t.dy * ratio) - border) / ratio;
    const float width = std::ceil(first.values[2] * t.m11 * ratio) + 2 * border + 1;
    const float height = std::ceil(first.values[3] * t.m22 * ratio) + 2 * border + 1;
    const auto limit = d2d_context_->GetMaximumBitmapSize();
    if (!std::isfinite(width) || !std::isfinite(height) || width <= 0 || height <= 0 ||
            width > limit || height > limit || width * height * 4 >
                (std::min)(128ULL * 1024 * 1024, budget / 4))
        return replay_scene(this, scene, t);
    SceneRaster cached;
    cached.bytes = static_cast<std::uint64_t>(width) * static_cast<std::uint64_t>(height) * 4;
    // Evict expired pages and least recently used scales before allocating.
    scene_rasters_.erase(std::remove_if(scene_rasters_.begin(), scene_rasters_.end(),
        [](const SceneRaster& entry) { return entry.identity.use_count() == 1; }), scene_rasters_.end());
    std::uint64_t total = cached.bytes;
    for (const auto& entry : scene_rasters_) total += entry.bytes;
    while (total > budget && !scene_rasters_.empty()) {
        auto oldest = std::min_element(scene_rasters_.begin(), scene_rasters_.end(),
            [](const SceneRaster& a, const SceneRaster& b) { return a.used < b.used; });
        total -= oldest->bytes;
        scene_rasters_.erase(oldest);
    }
    const auto properties = D2D1::BitmapProperties1(D2D1_BITMAP_OPTIONS_TARGET,
        D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED), dpi_, dpi_);
    auto result = d2d_context_->CreateBitmap(D2D1::SizeU(
        static_cast<UINT32>(width), static_cast<UINT32>(height)), nullptr, 0, properties, &cached.bitmap);
    if (FAILED(result)) return replay_scene(this, scene, t);
    ComPtr<ID2D1Image> previous;
    d2d_context_->GetTarget(&previous);
    d2d_context_->SetTarget(cached.bitmap.Get());
    d2d_context_->Clear(D2D1::ColorF(0, 0, 0, 0));
    auto local = t;
    local.dx -= origin_x;
    local.dy -= origin_y;
    result = replay_scene(this, scene, local);
    if (SUCCEEDED(result)) result = d2d_context_->Flush();
    d2d_context_->SetTarget(previous.Get());
    if (FAILED(result)) return result;
    cached.identity = scene->identity;
    cached.transform = t;
    // Store the raster origin directly in the translation fields.
    cached.transform.dx = t.dx - origin_x;
    cached.transform.dy = t.dy - origin_y;
    cached.dpi = dpi_;
    cached.used = ++raster_clock_;
    d2d_context_->SetTransform(D2D1::Matrix3x2F::Translation(origin_x, origin_y));
    d2d_context_->DrawBitmap(cached.bitmap.Get(), nullptr, 1.0f,
        D2D1_INTERPOLATION_MODE_NEAREST_NEIGHBOR);
    try { scene_rasters_.push_back(std::move(cached)); }
    catch (const std::bad_alloc&) { /* This frame is still valid without caching. */ }
    return set_transform(t.m11, t.m12, t.m21, t.m22, t.dx, t.dy);
}

}  // namespace

std::uint32_t spdf_d2d_abi_version() noexcept {
    return SPDF_D2D_ABI_VERSION;
}

std::int32_t spdf_d2d_probe(SpdfD2DInfo* info) noexcept {
    if (info == nullptr || info->struct_size < sizeof(SpdfD2DInfo)) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    reset_info(info);

    ComPtr<ID3D11Device> d3d_device;
    D3D_FEATURE_LEVEL feature_level = D3D_FEATURE_LEVEL_10_0;
    auto result = create_d3d_device(D3D_DRIVER_TYPE_HARDWARE, d3d_device, feature_level);
    if (SUCCEEDED(result)) {
        info->driver = SPDF_D2D_DRIVER_HARDWARE;
    } else {
        result = create_d3d_device(D3D_DRIVER_TYPE_WARP, d3d_device, feature_level);
        if (FAILED(result)) {
            info->last_hresult = static_cast<std::int32_t>(result);
            return static_cast<std::int32_t>(result);
        }
        info->driver = SPDF_D2D_DRIVER_WARP;
    }
    info->feature_level = static_cast<std::uint32_t>(feature_level);
    set_adapter_name(d3d_device.Get(), info);

    ComPtr<IDXGIDevice> dxgi_device;
    result = d3d_device.As(&dxgi_device);
    if (FAILED(result)) {
        info->last_hresult = static_cast<std::int32_t>(result);
        return static_cast<std::int32_t>(result);
    }

    D2D1_FACTORY_OPTIONS options{};
    ComPtr<ID2D1Factory1> d2d_factory;
    result = D2D1CreateFactory(
        D2D1_FACTORY_TYPE_SINGLE_THREADED,
        __uuidof(ID2D1Factory1),
        &options,
        reinterpret_cast<void**>(d2d_factory.GetAddressOf()));
    if (FAILED(result)) {
        info->last_hresult = static_cast<std::int32_t>(result);
        return static_cast<std::int32_t>(result);
    }

    ComPtr<ID2D1Device> d2d_device;
    result = d2d_factory->CreateDevice(dxgi_device.Get(), &d2d_device);
    if (FAILED(result)) {
        info->last_hresult = static_cast<std::int32_t>(result);
        return static_cast<std::int32_t>(result);
    }

    ComPtr<ID2D1DeviceContext> d2d_context;
    result = d2d_device->CreateDeviceContext(
        D2D1_DEVICE_CONTEXT_OPTIONS_NONE,
        &d2d_context);
    if (FAILED(result)) {
        info->last_hresult = static_cast<std::int32_t>(result);
        return static_cast<std::int32_t>(result);
    }

    ComPtr<IDWriteFactory> dwrite_factory;
    result = DWriteCreateFactory(
        DWRITE_FACTORY_TYPE_SHARED,
        __uuidof(IDWriteFactory),
        reinterpret_cast<IUnknown**>(dwrite_factory.GetAddressOf()));
    info->last_hresult = static_cast<std::int32_t>(result);
    return static_cast<std::int32_t>(result);
}

std::int32_t spdf_d2d_create_surface(
    std::uintptr_t hwnd,
    std::uint32_t width,
    std::uint32_t height,
    float dpi,
    SpdfD2DInfo* info,
    void** surface) noexcept {
    if (hwnd == 0 || info == nullptr || info->struct_size < sizeof(SpdfD2DInfo) ||
            surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    *surface = nullptr;
    reset_info(info);
    auto context = new (std::nothrow) Surface();
    if (context == nullptr) {
        info->last_hresult = static_cast<std::int32_t>(E_OUTOFMEMORY);
        return static_cast<std::int32_t>(E_OUTOFMEMORY);
    }
    const auto result = context->initialize(
        reinterpret_cast<HWND>(hwnd), width, height, dpi, info);
    info->last_hresult = static_cast<std::int32_t>(result);
    if (FAILED(result)) {
        delete context;
        return static_cast<std::int32_t>(result);
    }
    *surface = context;
    return static_cast<std::int32_t>(S_OK);
}

std::int32_t spdf_d2d_resize_surface(
    void* surface,
    std::uint32_t width,
    std::uint32_t height,
    float dpi) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->resize(width, height, dpi));
}

std::int32_t spdf_d2d_clear_surface(void* surface, std::uint32_t argb) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->clear(argb));
}

std::int32_t spdf_d2d_begin_frame(void* surface, std::uint32_t argb) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->begin_frame(argb));
}

std::int32_t spdf_d2d_set_transform(
    void* surface,
    float m11,
    float m12,
    float m21,
    float m22,
    float dx,
    float dy) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->set_transform(
        m11, m12, m21, m22, dx, dy));
}

std::int32_t spdf_d2d_create_bitmap(
    void* surface,
    const void* bgra_pixels,
    std::uint32_t width,
    std::uint32_t height,
    std::uint32_t stride,
    void** bitmap) noexcept {
    if (surface == nullptr || bitmap == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->create_bitmap(
        bgra_pixels,
        width,
        height,
        stride,
        reinterpret_cast<Surface::Bitmap**>(bitmap)));
}

std::int32_t spdf_d2d_create_path(
    void* surface,
    const SpdfD2DPathCommand* commands,
    std::uint32_t command_count,
    std::uint32_t even_odd,
    void** path) noexcept {
    if (surface == nullptr || path == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->create_path(
        commands,
        command_count,
        even_odd != 0,
        reinterpret_cast<Surface::Path**>(path)));
}

std::int32_t spdf_d2d_create_geometry_group(
    void* surface,
    void* const* paths,
    const SpdfD2DTransform* transforms,
    std::uint32_t path_count,
    std::uint32_t even_odd,
    void** group) noexcept {
    if (surface == nullptr || paths == nullptr || transforms == nullptr ||
            group == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->create_geometry_group(
            reinterpret_cast<Surface::Path* const*>(paths), transforms,
            path_count, even_odd != 0,
            reinterpret_cast<Surface::Path**>(group)));
}

std::int32_t spdf_d2d_create_stroke_style(
    void* surface,
    std::uint32_t start_cap,
    std::uint32_t dash_cap,
    std::uint32_t end_cap,
    std::uint32_t line_join,
    float miter_limit,
    float dash_offset,
    const float* dashes,
    std::uint32_t dash_count,
    void** stroke_style) noexcept {
    if (surface == nullptr || stroke_style == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->create_stroke_style(
            start_cap, dash_cap, end_cap, line_join, miter_limit, dash_offset,
            dashes, dash_count,
            reinterpret_cast<Surface::StrokeStyle**>(stroke_style)));
}

std::int32_t spdf_d2d_create_stroked_path(
    void* surface,
    void* path,
    float width,
    void* stroke_style,
    void** stroked_path) noexcept {
    if (surface == nullptr || path == nullptr || stroked_path == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->create_stroked_path(
            static_cast<Surface::Path*>(path), width,
            static_cast<Surface::StrokeStyle*>(stroke_style),
            reinterpret_cast<Surface::Path**>(stroked_path)));
}

std::int32_t spdf_d2d_push_clip_path(void* surface, void* path) noexcept {
    if (surface == nullptr || path == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->push_clip_path(
            static_cast<Surface::Path*>(path)));
}

std::int32_t spdf_d2d_pop_clip(void* surface) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->pop_clip());
}

std::int32_t spdf_d2d_push_opacity_layer(
    void* surface,
    float opacity) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->push_opacity_layer(opacity));
}

std::int32_t spdf_d2d_pop_layer(void* surface) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->pop_layer());
}

std::int32_t spdf_d2d_begin_mask(
    void* surface,
    float left,
    float top,
    float right,
    float bottom,
    std::uint32_t luminosity,
    std::uint32_t background_argb) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->begin_mask(
            left, top, right, bottom, luminosity != 0, background_argb));
}

std::int32_t spdf_d2d_end_mask(
    void* surface, const float* alpha_transfer, std::uint32_t transfer_count) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->end_mask(alpha_transfer, transfer_count));
}

std::int32_t spdf_d2d_begin_composite_group(
    void* surface, std::uint32_t mode, float opacity, std::uint32_t group_flags) noexcept {
    if (surface == nullptr || (group_flags & ~3U) != 0)
        return static_cast<std::int32_t>(E_INVALIDARG);
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->begin_composite_group(
            mode, opacity, nullptr, false, (group_flags & 1) != 0, nullptr,
            (group_flags & 2) != 0));
}

std::int32_t spdf_d2d_end_composite_group(void* surface) noexcept {
    if (surface == nullptr) return static_cast<std::int32_t>(E_INVALIDARG);
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->end_composite_group());
}

std::int32_t spdf_d2d_begin_clip_group(void* surface, void* path) noexcept {
    if (surface == nullptr || path == nullptr) return static_cast<std::int32_t>(E_INVALIDARG);
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->begin_composite_group(
        0, 1.0f, static_cast<Surface::Path*>(path)));
}

std::int32_t spdf_d2d_end_clip_group(void* surface) noexcept {
    if (surface == nullptr) return static_cast<std::int32_t>(E_INVALIDARG);
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->end_composite_group(true));
}

std::int32_t spdf_d2d_begin_composite_mask(
    void* surface, float left, float top, float right, float bottom,
    std::uint32_t luminosity, std::uint32_t background_argb) noexcept {
    if (surface == nullptr) return static_cast<std::int32_t>(E_INVALIDARG);
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->begin_composite_mask(
        left, top, right, bottom, luminosity != 0, background_argb));
}

std::int32_t spdf_d2d_end_composite_mask(
    void* surface, const float* alpha_transfer, std::uint32_t transfer_count) noexcept {
    if (surface == nullptr) return static_cast<std::int32_t>(E_INVALIDARG);
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->end_composite_mask(
        alpha_transfer, transfer_count));
}

std::int32_t spdf_d2d_set_luminosity_lut(
    void* surface, const unsigned char* data, std::uint32_t size, std::uint32_t edge) noexcept {
    if (surface == nullptr) return static_cast<std::int32_t>(E_INVALIDARG);
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->set_luminosity_lut(
        data, size, edge));
}

std::int32_t spdf_d2d_read_pixels(
    void* surface, void* pixels, std::size_t size) noexcept {
    if (surface == nullptr) return static_cast<std::int32_t>(E_INVALIDARG);
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->read_pixels(pixels, size));
}

std::int32_t spdf_d2d_draw_bitmap(
    void* surface,
    void* bitmap,
    float left,
    float top,
    float right,
    float bottom,
    float opacity, std::uint32_t interpolate) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->draw_bitmap(
        static_cast<Surface::Bitmap*>(bitmap),
        left,
        top,
        right,
        bottom,
        opacity, interpolate != 0));
}

std::int32_t spdf_d2d_fill_rect(
    void* surface,
    float left,
    float top,
    float right,
    float bottom,
    std::uint32_t argb) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->fill_rect(
        left, top, right, bottom, argb));
}

std::int32_t spdf_d2d_stroke_rect(
    void* surface,
    float left,
    float top,
    float right,
    float bottom,
    std::uint32_t argb,
    float width) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->stroke_rect(
        left, top, right, bottom, argb, width));
}

std::int32_t spdf_d2d_fill_path(
    void* surface,
    void* path,
    std::uint32_t argb) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->fill_path(
        static_cast<Surface::Path*>(path), argb));
}

std::int32_t spdf_d2d_stroke_path(
    void* surface,
    void* path,
    std::uint32_t argb,
    float width) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->stroke_path(
        static_cast<Surface::Path*>(path), argb, width));
}

std::int32_t spdf_d2d_stroke_path_styled(
    void* surface,
    void* path,
    std::uint32_t argb,
    float width,
    void* stroke_style) noexcept {
    if (surface == nullptr || stroke_style == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->stroke_path(
        static_cast<Surface::Path*>(path), argb, width,
        static_cast<Surface::StrokeStyle*>(stroke_style)));
}

std::int32_t spdf_d2d_fill_linear_gradient(
    void* surface,
    void* path,
    float start_x,
    float start_y,
    float end_x,
    float end_y,
    const SpdfD2DGradientStop* stops,
    std::uint32_t stop_count) noexcept {
    if (surface == nullptr || path == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->fill_linear_gradient(
            static_cast<Surface::Path*>(path), start_x, start_y,
            end_x, end_y, stops, stop_count));
}

std::int32_t spdf_d2d_fill_radial_gradient(
    void* surface,
    void* path,
    float center_x,
    float center_y,
    float origin_x,
    float origin_y,
    float radius_x,
    float radius_y,
    const SpdfD2DGradientStop* stops,
    std::uint32_t stop_count) noexcept {
    if (surface == nullptr || path == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(
        static_cast<Surface*>(surface)->fill_radial_gradient(
        static_cast<Surface::Path*>(path), center_x, center_y,
            origin_x, origin_y, radius_x, radius_y, stops, stop_count));
}

std::int32_t spdf_d2d_create_scene(
    void* surface,
    const SpdfD2DSceneCommand* commands,
    std::uint32_t command_count,
    void** scene) noexcept {
    if (surface == nullptr || commands == nullptr || command_count == 0 || scene == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    *scene = nullptr;
    try {
        auto created = std::make_unique<Scene>();
        created->owner = static_cast<Surface*>(surface);
        created->commands.reserve(command_count);
        for (std::uint32_t index = 0; index < command_count; ++index) {
            SceneCommand stored{};
            stored.command = commands[index];
            stored.command.data = nullptr;
            const auto type = commands[index].type;
            if (type < SPDF_D2D_SCENE_FILL_RECT ||
                    type > SPDF_D2D_SCENE_RECT_CLIP_POP) {
                return static_cast<std::int32_t>(E_INVALIDARG);
            }
            if (type == SPDF_D2D_SCENE_COMPOSITE_PUSH ||
                    type == SPDF_D2D_SCENE_COMPOSITE_POP ||
                    type == SPDF_D2D_SCENE_CLIP_GROUP_PUSH ||
                    type == SPDF_D2D_SCENE_CLIP_GROUP_POP ||
                    type == SPDF_D2D_SCENE_MASK_BEGIN ||
                    type == SPDF_D2D_SCENE_MASK_END ||
                    type == SPDF_D2D_SCENE_COMPOSITE_MASK_BEGIN ||
                    type == SPDF_D2D_SCENE_COMPOSITE_MASK_END) {
                created->recordable = false;
            }
            if (type == SPDF_D2D_SCENE_BITMAP) {
                const auto* source = static_cast<Surface::Bitmap*>(commands[index].resource);
                if (source == nullptr || source->owner != created->owner || !source->resource) {
                    return static_cast<std::int32_t>(E_INVALIDARG);
                }
                stored.bitmap = std::make_unique<Surface::Bitmap>(
                    Surface::Bitmap{created->owner, source->resource});
                stored.command.resource = stored.bitmap.get();
            } else if (type == SPDF_D2D_SCENE_CLIP_PUSH ||
                    type == SPDF_D2D_SCENE_CLIP_GROUP_PUSH ||
                    type == SPDF_D2D_SCENE_PATH_FILL ||
                    type == SPDF_D2D_SCENE_PATH_STROKE ||
                    type == SPDF_D2D_SCENE_LINEAR_GRADIENT ||
                    type == SPDF_D2D_SCENE_RADIAL_GRADIENT) {
                const auto* source = static_cast<Surface::Path*>(commands[index].resource);
                if (source == nullptr || source->owner != created->owner || !source->resource) {
                    return static_cast<std::int32_t>(E_INVALIDARG);
                }
                stored.path = std::make_unique<Surface::Path>(Surface::Path{
                    created->owner, source->resource, source->fill_realization});
                stored.command.resource = stored.path.get();
            }
            if (type == SPDF_D2D_SCENE_PATH_STROKE && commands[index].stroke_style != nullptr) {
                const auto* source = static_cast<Surface::StrokeStyle*>(commands[index].stroke_style);
                if (source->owner != created->owner || !source->resource) {
                    return static_cast<std::int32_t>(E_INVALIDARG);
                }
                stored.stroke_style = std::make_unique<Surface::StrokeStyle>(
                    Surface::StrokeStyle{created->owner, source->resource});
                stored.command.stroke_style = stored.stroke_style.get();
            }
            if (commands[index].data_count != 0 && commands[index].data == nullptr) {
                return static_cast<std::int32_t>(E_INVALIDARG);
            }
            if (commands[index].type == SPDF_D2D_SCENE_LINEAR_GRADIENT ||
                    commands[index].type == SPDF_D2D_SCENE_RADIAL_GRADIENT) {
                if (commands[index].data_count < 2 ||
                        commands[index].data_count > 256) {
                    return static_cast<std::int32_t>(E_INVALIDARG);
                }
                const auto* first = static_cast<const SpdfD2DGradientStop*>(commands[index].data);
                if (commands[index].data_count != 0) {
                    stored.stops.assign(first, first + commands[index].data_count);
                }
                HRESULT result = S_OK;
                if (commands[index].type == SPDF_D2D_SCENE_LINEAR_GRADIENT) {
                    result = created->owner->create_linear_gradient_brush(
                        commands[index].values[0], commands[index].values[1],
                        commands[index].values[2], commands[index].values[3],
                        stored.stops.data(),
                        static_cast<std::uint32_t>(stored.stops.size()),
                        &stored.linear_brush);
                } else {
                    result = created->owner->create_radial_gradient_brush(
                        commands[index].values[0], commands[index].values[1],
                        commands[index].values[2], commands[index].values[3],
                        commands[index].values[4], commands[index].values[5],
                        stored.stops.data(),
                        static_cast<std::uint32_t>(stored.stops.size()),
                        &stored.radial_brush);
                }
                if (FAILED(result)) return static_cast<std::int32_t>(result);
            } else if (commands[index].type == SPDF_D2D_SCENE_MASK_END ||
                    commands[index].type == SPDF_D2D_SCENE_COMPOSITE_MASK_END) {
                if (commands[index].data_count == 1) {
                    return static_cast<std::int32_t>(E_INVALIDARG);
                }
                const auto* first = static_cast<const float*>(commands[index].data);
                if (commands[index].data_count != 0) {
                    stored.transfer.assign(first, first + commands[index].data_count);
                }
            } else if (commands[index].data_count != 0) {
                return static_cast<std::int32_t>(E_INVALIDARG);
            }
            created->commands.push_back(std::move(stored));
        }
        *scene = created.release();
        return static_cast<std::int32_t>(S_OK);
    } catch (const std::bad_alloc&) {
        return static_cast<std::int32_t>(E_OUTOFMEMORY);
    } catch (...) {
        return static_cast<std::int32_t>(E_FAIL);
    }
}

std::int32_t spdf_d2d_draw_scene_preview(
    void* surface,
    void* scene,
    const SpdfD2DTransform* transform) noexcept {
    if (!surface || !scene || !transform) return static_cast<std::int32_t>(E_INVALIDARG);
    auto* context = static_cast<Surface*>(surface);
    auto* retained = static_cast<Scene*>(scene);
    if (retained->owner != context) return static_cast<std::int32_t>(E_INVALIDARG);
    return static_cast<std::int32_t>(context->draw_scene_preview(retained, *transform));
}

std::int32_t spdf_d2d_draw_scene(
    void* surface,
    void* scene,
    const SpdfD2DTransform* transform) noexcept {
    if (surface == nullptr || scene == nullptr || transform == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    auto* context = static_cast<Surface*>(surface);
    auto* retained = static_cast<Scene*>(scene);
    if (retained->owner != context) return static_cast<std::int32_t>(E_INVALIDARG);
    if (!retained->recordable) {
        return static_cast<std::int32_t>(context->draw_cached_scene(retained, *transform));
    }
    if (!retained->display_list) {
        ComPtr<ID2D1Image> previous_target;
        ComPtr<ID2D1CommandList> commands;
        auto result = context->begin_scene_recording(&previous_target, &commands);
        if (FAILED(result)) return static_cast<std::int32_t>(result);
        const SpdfD2DTransform identity{1, 0, 0, 1, 0, 0};
        result = replay_scene(context, retained, identity);
        const auto close_result = context->end_scene_recording(
            previous_target.Get(), commands.Get());
        if (FAILED(result)) return static_cast<std::int32_t>(result);
        if (FAILED(close_result)) return static_cast<std::int32_t>(close_result);
        retained->display_list = commands;
    }
    return static_cast<std::int32_t>(
        context->draw_command_list(retained->display_list.Get(), *transform));
}

std::int32_t spdf_d2d_end_frame(void* surface) noexcept {
    if (surface == nullptr) {
        return static_cast<std::int32_t>(E_INVALIDARG);
    }
    return static_cast<std::int32_t>(static_cast<Surface*>(surface)->end_frame());
}

void spdf_d2d_destroy_bitmap(void* bitmap) noexcept {
    delete static_cast<Surface::Bitmap*>(bitmap);
}

void spdf_d2d_destroy_path(void* path) noexcept {
    delete static_cast<Surface::Path*>(path);
}

void spdf_d2d_destroy_stroke_style(void* stroke_style) noexcept {
    delete static_cast<Surface::StrokeStyle*>(stroke_style);
}

void spdf_d2d_destroy_scene(void* scene) noexcept {
    delete static_cast<Scene*>(scene);
}

void spdf_d2d_destroy_surface(void* surface) noexcept {
    delete static_cast<Surface*>(surface);
}
