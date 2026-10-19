#pragma once

#include <algorithm>
#include <atomic>
#include <new>
#include <d2d1_1.h>
#include <d2d1effectauthor.h>
#include "spdf_mask_lerp_shader.h"

namespace {

constexpr GUID CLSID_SpdfMaskLerp = {0x4a84aca5,0x6d34,0x45ad,{0x9e,0x78,0x23,0x72,0xa1,0x13,0x50,0x2a}};
constexpr GUID GUID_SpdfMaskLerpShader = {0x71410267,0xb05b,0x4f80,{0x9d,0xbc,0x64,0x20,0xe1,0x3f,0x2b,0x4d}};

class MaskLerpEffect final : public ID2D1EffectImpl, public ID2D1DrawTransform {
public:
    static HRESULT CALLBACK Create(IUnknown** output) noexcept {
        if (!output) return E_POINTER;
        auto value = new (std::nothrow) MaskLerpEffect();
        *output = value ? static_cast<ID2D1EffectImpl*>(value) : nullptr;
        return value ? S_OK : E_OUTOFMEMORY;
    }
    static HRESULT Register(ID2D1Factory1* factory) noexcept {
        const auto xml = LR"xml(<?xml version="1.0"?>
<Effect>
  <Property name="DisplayName" type="string" value="sPDF Mask Lerp"/>
  <Property name="Author" type="string" value="Leaflet"/>
  <Property name="Category" type="string" value="Composite"/>
  <Property name="Description" type="string" value="Premultiplied backdrop/coverage interpolation"/>
  <Inputs><Input name="Backdrop"/><Input name="Source"/><Input name="Mask"/></Inputs>
</Effect>)xml";
        return factory->RegisterEffectFromString(CLSID_SpdfMaskLerp, xml, nullptr, 0, Create);
    }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** output) override {
        if (!output) return E_POINTER;
        *output = nullptr;
        if (iid == __uuidof(IUnknown) || iid == __uuidof(ID2D1EffectImpl))
            *output = static_cast<ID2D1EffectImpl*>(this);
        else if (iid == __uuidof(ID2D1DrawTransform)) *output = static_cast<ID2D1DrawTransform*>(this);
        else if (iid == __uuidof(ID2D1Transform)) *output = static_cast<ID2D1Transform*>(this);
        else if (iid == __uuidof(ID2D1TransformNode)) *output = static_cast<ID2D1TransformNode*>(this);
        else return E_NOINTERFACE;
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++references_; }
    ULONG STDMETHODCALLTYPE Release() override {
        const auto count = --references_;
        if (!count) delete this;
        return count;
    }
    HRESULT STDMETHODCALLTYPE Initialize(ID2D1EffectContext* context, ID2D1TransformGraph* graph) override {
        auto result = S_OK;
        if (!context->IsShaderLoaded(GUID_SpdfMaskLerpShader)) {
            result = context->LoadPixelShader(GUID_SpdfMaskLerpShader, spdf_mask_lerp_shader,
                static_cast<UINT32>(sizeof(spdf_mask_lerp_shader)));
        }
        if (SUCCEEDED(result)) result = graph->SetSingleTransformNode(this);
        return result;
    }
    HRESULT STDMETHODCALLTYPE PrepareForRender(D2D1_CHANGE_TYPE) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetGraph(ID2D1TransformGraph*) override { return E_NOTIMPL; }
    UINT32 STDMETHODCALLTYPE GetInputCount() const override { return 3; }
    HRESULT STDMETHODCALLTYPE SetDrawInfo(ID2D1DrawInfo* info) override {
        for (UINT32 i = 0; i < 3; ++i) {
            const auto result = info->SetInputDescription(i, {D2D1_FILTER_MIN_MAG_MIP_POINT, 1});
            if (FAILED(result)) return result;
        }
        return info->SetPixelShader(GUID_SpdfMaskLerpShader);
    }
    HRESULT STDMETHODCALLTYPE MapOutputRectToInputRects(const D2D1_RECT_L* output,
            D2D1_RECT_L* inputs, UINT32 count) const override {
        if (!output || !inputs || count != 3) return E_INVALIDARG;
        for (UINT32 i = 0; i < count; ++i) inputs[i] = *output;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE MapInputRectsToOutputRect(const D2D1_RECT_L* inputs,
            const D2D1_RECT_L*, UINT32 count, D2D1_RECT_L* output, D2D1_RECT_L* opaque) override {
        if (!inputs || !output || !opaque || count != 3) return E_INVALIDARG;
        *output = inputs[0];
        for (UINT32 i = 1; i < count; ++i) {
            output->left = (std::max)(output->left, inputs[i].left);
            output->top = (std::max)(output->top, inputs[i].top);
            output->right = (std::min)(output->right, inputs[i].right);
            output->bottom = (std::min)(output->bottom, inputs[i].bottom);
        }
        *opaque = {};
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE MapInvalidRect(UINT32 index, D2D1_RECT_L input,
            D2D1_RECT_L* output) const override {
        if (!output || index >= 3) return E_INVALIDARG;
        *output = input;
        return S_OK;
    }
private:
    std::atomic<ULONG> references_{1};
};

} // namespace
