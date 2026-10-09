#pragma once

#include <cstddef>
#include <cstdint>

#ifdef SPDF_D2D_EXPORTS
#define SPDF_D2D_API extern "C" __declspec(dllexport)
#else
#define SPDF_D2D_API extern "C" __declspec(dllimport)
#endif

constexpr std::uint32_t SPDF_D2D_ABI_VERSION = 24;
constexpr std::uint32_t SPDF_D2D_ADAPTER_NAME_LENGTH = 128;

enum SpdfD2DDriver : std::uint32_t {
    SPDF_D2D_DRIVER_NONE = 0,
    SPDF_D2D_DRIVER_HARDWARE = 1,
    SPDF_D2D_DRIVER_WARP = 2,
};

struct SpdfD2DInfo {
    std::uint32_t struct_size;
    std::uint32_t abi_version;
    std::uint32_t driver;
    std::uint32_t feature_level;
    std::int32_t last_hresult;
    wchar_t adapter_name[SPDF_D2D_ADAPTER_NAME_LENGTH];
};

enum SpdfD2DPathCommandType : std::uint32_t {
    SPDF_D2D_PATH_MOVE = 1,
    SPDF_D2D_PATH_LINE = 2,
    SPDF_D2D_PATH_CUBIC = 3,
    SPDF_D2D_PATH_CLOSE = 4,
};

struct SpdfD2DPathCommand {
    std::uint32_t type;
    float points[6];
};

struct SpdfD2DTransform {
    float m11;
    float m12;
    float m21;
    float m22;
    float dx;
    float dy;
};

struct SpdfD2DGradientStop {
    float position;
    std::uint32_t argb;
};

enum SpdfD2DSceneCommandType : std::uint32_t {
    SPDF_D2D_SCENE_FILL_RECT = 1,
    SPDF_D2D_SCENE_CLIP_PUSH = 2,
    SPDF_D2D_SCENE_CLIP_POP = 3,
    SPDF_D2D_SCENE_OPACITY_PUSH = 4,
    SPDF_D2D_SCENE_LAYER_POP = 5,
    SPDF_D2D_SCENE_COMPOSITE_PUSH = 6,
    SPDF_D2D_SCENE_COMPOSITE_POP = 7,
    SPDF_D2D_SCENE_CLIP_GROUP_PUSH = 8,
    SPDF_D2D_SCENE_CLIP_GROUP_POP = 9,
    SPDF_D2D_SCENE_MASK_BEGIN = 10,
    SPDF_D2D_SCENE_MASK_END = 11,
    SPDF_D2D_SCENE_COMPOSITE_MASK_BEGIN = 12,
    SPDF_D2D_SCENE_COMPOSITE_MASK_END = 13,
    SPDF_D2D_SCENE_BITMAP = 14,
    SPDF_D2D_SCENE_PATH_FILL = 15,
    SPDF_D2D_SCENE_PATH_STROKE = 16,
    SPDF_D2D_SCENE_LINEAR_GRADIENT = 17,
    SPDF_D2D_SCENE_RADIAL_GRADIENT = 18,
    SPDF_D2D_SCENE_RECT_CLIP_PUSH = 19,
    SPDF_D2D_SCENE_RECT_CLIP_POP = 20,
};

constexpr std::uint32_t SPDF_D2D_SCENE_HAS_TRANSFORM = 1;

struct SpdfD2DSceneCommand {
    std::uint32_t type;
    std::uint32_t flags;
    void* resource;
    void* stroke_style;
    SpdfD2DTransform transform;
    float values[8];
    std::uint32_t uint_values[4];
    const void* data;
    std::uint32_t data_count;
};

static_assert(sizeof(wchar_t) == 2, "The sPDF D2D ABI requires Windows wchar_t");
static_assert(offsetof(SpdfD2DInfo, adapter_name) == 20, "Unexpected D2D ABI layout");
static_assert(sizeof(SpdfD2DInfo) == 276, "Unexpected D2D ABI size");
static_assert(sizeof(SpdfD2DPathCommand) == 28, "Unexpected path command layout");
static_assert(sizeof(SpdfD2DTransform) == 24, "Unexpected transform layout");
static_assert(sizeof(SpdfD2DGradientStop) == 8, "Unexpected gradient stop layout");
static_assert(offsetof(SpdfD2DSceneCommand, data) == 96, "Unexpected scene command layout");
static_assert(sizeof(SpdfD2DSceneCommand) == 112, "Unexpected scene command size");

SPDF_D2D_API std::uint32_t spdf_d2d_abi_version() noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_probe(SpdfD2DInfo* info) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_create_surface(
    std::uintptr_t hwnd,
    std::uint32_t width,
    std::uint32_t height,
    float dpi,
    SpdfD2DInfo* info,
    void** surface) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_resize_surface(
    void* surface,
    std::uint32_t width,
    std::uint32_t height,
    float dpi) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_clear_surface(
    void* surface,
    std::uint32_t argb) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_begin_frame(
    void* surface,
    std::uint32_t argb) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_set_transform(
    void* surface,
    float m11,
    float m12,
    float m21,
    float m22,
    float dx,
    float dy) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_create_bitmap(
    void* surface,
    const void* bgra_pixels,
    std::uint32_t width,
    std::uint32_t height,
    std::uint32_t stride,
    void** bitmap) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_create_path(
    void* surface,
    const SpdfD2DPathCommand* commands,
    std::uint32_t command_count,
    std::uint32_t even_odd,
    void** path) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_create_geometry_group(
    void* surface,
    void* const* paths,
    const SpdfD2DTransform* transforms,
    std::uint32_t path_count,
    std::uint32_t even_odd,
    void** group) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_create_stroke_style(
    void* surface,
    std::uint32_t start_cap,
    std::uint32_t dash_cap,
    std::uint32_t end_cap,
    std::uint32_t line_join,
    float miter_limit,
    float dash_offset,
    const float* dashes,
    std::uint32_t dash_count,
    void** stroke_style) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_create_stroked_path(
    void* surface,
    void* path,
    float width,
    void* stroke_style,
    void** stroked_path) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_push_clip_path(
    void* surface,
    void* path) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_pop_clip(void* surface) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_push_opacity_layer(
    void* surface,
    float opacity) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_pop_layer(void* surface) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_begin_mask(
    void* surface,
    float left,
    float top,
    float right,
    float bottom,
    std::uint32_t luminosity,
    std::uint32_t background_argb) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_end_mask(
    void* surface, const float* alpha_transfer, std::uint32_t transfer_count) noexcept;
// ABI 20 flags: bit 0 = knockout, bit 1 = non-isolated Normal group.
SPDF_D2D_API std::int32_t spdf_d2d_begin_composite_group(
    void* surface, std::uint32_t mode, float opacity, std::uint32_t group_flags) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_end_composite_group(void* surface) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_begin_clip_group(void* surface, void* path) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_end_clip_group(void* surface) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_begin_composite_mask(
    void* surface, float left, float top, float right, float bottom,
    std::uint32_t luminosity, std::uint32_t background_argb) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_end_composite_mask(
    void* surface, const float* alpha_transfer, std::uint32_t transfer_count) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_set_luminosity_lut(
    void* surface, const unsigned char* data, std::uint32_t size, std::uint32_t edge) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_read_pixels(
    void* surface, void* pixels, std::size_t size) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_draw_bitmap(
    void* surface,
    void* bitmap,
    float left,
    float top,
    float right,
    float bottom,
    float opacity, std::uint32_t interpolate) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_fill_rect(
    void* surface,
    float left,
    float top,
    float right,
    float bottom,
    std::uint32_t argb) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_stroke_rect(
    void* surface,
    float left,
    float top,
    float right,
    float bottom,
    std::uint32_t argb,
    float width) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_fill_path(
    void* surface,
    void* path,
    std::uint32_t argb) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_stroke_path(
    void* surface,
    void* path,
    std::uint32_t argb,
    float width) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_stroke_path_styled(
    void* surface,
    void* path,
    std::uint32_t argb,
    float width,
    void* stroke_style) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_fill_linear_gradient(
    void* surface,
    void* path,
    float start_x,
    float start_y,
    float end_x,
    float end_y,
    const SpdfD2DGradientStop* stops,
    std::uint32_t stop_count) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_fill_radial_gradient(
    void* surface,
    void* path,
    float center_x,
    float center_y,
    float origin_x,
    float origin_y,
    float radius_x,
    float radius_y,
    const SpdfD2DGradientStop* stops,
    std::uint32_t stop_count) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_create_scene(
    void* surface,
    const SpdfD2DSceneCommand* commands,
    std::uint32_t command_count,
    void** scene) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_draw_scene(
    void* surface,
    void* scene,
    const SpdfD2DTransform* transform) noexcept;

// S_OK when an existing complex-scene raster was drawn; S_FALSE otherwise.
SPDF_D2D_API std::int32_t spdf_d2d_draw_scene_preview(
    void* surface,
    void* scene,
    const SpdfD2DTransform* transform) noexcept;
// Display mode: reuse bounded transparency-group snapshots across zoom scales.
SPDF_D2D_API std::int32_t spdf_d2d_draw_scene_cached(
    void* surface,
    void* scene,
    const SpdfD2DTransform* transform) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_request_sharp(
    void* surface, void* scene, const SpdfD2DTransform* transform) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_draw_sharp(
    void* surface, void* scene, const SpdfD2DTransform* transform) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_draw_sharp_partial(
    void* surface, void* scene, const SpdfD2DTransform* transform) noexcept;
// 0: idle/cancelled, 1: pending, 2: completed, 3: partial update (still pending).
// Negative values are HRESULT errors.
SPDF_D2D_API std::int32_t spdf_d2d_sharp_status(void* surface) noexcept;
SPDF_D2D_API void spdf_d2d_cancel_sharp(void* surface) noexcept;
SPDF_D2D_API std::int32_t spdf_d2d_end_frame(void* surface) noexcept;
SPDF_D2D_API void spdf_d2d_destroy_bitmap(void* bitmap) noexcept;
SPDF_D2D_API void spdf_d2d_destroy_path(void* path) noexcept;
SPDF_D2D_API void spdf_d2d_destroy_stroke_style(void* stroke_style) noexcept;
SPDF_D2D_API void spdf_d2d_destroy_scene(void* scene) noexcept;
SPDF_D2D_API void spdf_d2d_destroy_surface(void* surface) noexcept;
