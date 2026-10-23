#pragma once

// Conservative capture lifetimes; dimensions are advisory.
// Replay still determines all actual sizes, and unmatched requests fall back.
bool prepare_storage_plan(Surface *surface, Scene *scene, const SpdfD2DTransform &page,
                          const TilePlan &plan) noexcept {
    struct Frame {
        UINT32 width, height;
        D2D1_MATRIX_3X2_F previous;
        D2D1_POINT_2F origin{};
        bool cropped = false, building = false, isolated = false;
        D2D1_PRIMITIVE_BLEND blend = D2D1_PRIMITIVE_BLEND_SOURCE_OVER;
        std::size_t key = SIZE_MAX;
        UINT targets = 0, plain = 0;
    };
    struct Count {
        ScratchStorageNeed need{};
        UINT live_target = 0, live_plain = 0, uses = 0;
    };
    try {
        std::vector<Frame> stack;
        std::vector<Count> counts;
        const auto size = surface->storage_target_size();
        UINT32 width = size.width, height = size.height;
        const auto dpi = surface->storage_dpi();
        auto matrix = D2D1::Matrix3x2F::Identity();
        auto blend = D2D1_PRIMITIVE_BLEND_SOURCE_OVER;
        const auto adjusted = [&](const SpdfD2DSceneCommand &c) {
            auto m =
                (c.flags & SPDF_D2D_SCENE_HAS_TRANSFORM)
                    ? compose_transform(page, c.transform)
                    : D2D1::Matrix3x2F(page.m11, page.m12, page.m21, page.m22, page.dx, page.dy);
            for (const auto &f : stack)
                if (f.cropped) {
                    m._31 -= f.origin.x;
                    m._32 -= f.origin.y;
                }
            return *D2D1::Matrix3x2F::ReinterpretBaseType(&m);
        };
        const auto add = [&](Frame &f, UINT targets, UINT plain) {
            if (!targets && !plain)
                return;
            std::size_t k = 0;
            for (; k < counts.size(); ++k)
                if (counts[k].need.width == width && counts[k].need.height == height)
                    break;
            if (k == counts.size()) {
                if (k >= 4096)
                    throw std::bad_alloc();
                Count c;
                c.need.width = width;
                c.need.height = height;
                counts.push_back(c);
            }
            auto &c = counts[k];
            c.live_target += targets;
            c.live_plain += plain;
            c.uses += targets + plain;
            c.need.targets = (std::max)(c.need.targets, c.live_target);
            c.need.plain = (std::max)(c.need.plain, c.live_plain);
            f.key = k;
            f.targets = targets;
            f.plain = plain;
        };
        for (auto index : plan.commands) {
            if (surface->cancelled())
                return false;
            const auto &stored = scene->data->commands[index];
            const auto &c = stored.command;
            const auto role = scene->replay->replay_roles[index];
            if ((role & Scene::FusedClipBoundary) && !stack.empty() && stack.back().isolated)
                continue;
            if (role & Scene::Noop)
                continue;
            if (role & Scene::SimpleOpen) {
                matrix = adjusted(c);
                continue;
            }
            if (role & Scene::SimpleEnd)
                continue;
            switch (c.type) {
            case SPDF_D2D_SCENE_FILL_RECT:
            case SPDF_D2D_SCENE_CLIP_PUSH:
            case SPDF_D2D_SCENE_OPACITY_PUSH:
            case SPDF_D2D_SCENE_RECT_CLIP_PUSH:
            case SPDF_D2D_SCENE_BITMAP:
            case SPDF_D2D_SCENE_PATH_FILL:
            case SPDF_D2D_SCENE_PATH_STROKE:
            case SPDF_D2D_SCENE_LINEAR_GRADIENT:
            case SPDF_D2D_SCENE_RADIAL_GRADIENT:
                matrix = adjusted(c);
                break;
            case SPDF_D2D_SCENE_MASK_BEGIN:
            case SPDF_D2D_SCENE_MASK_END:
                return false; // Command-list masks retain the original allocator.
            case SPDF_D2D_SCENE_COMPOSITE_MASK_END:
                if (stack.empty() || !stack.back().building)
                    return false;
                matrix = D2D1::Matrix3x2F::Identity();
                for (const auto &f : stack)
                    if (f.cropped) {
                        matrix._31 -= f.origin.x;
                        matrix._32 -= f.origin.y;
                    }
                stack.back().building = false;
                break;
            case SPDF_D2D_SCENE_COMPOSITE_POP:
            case SPDF_D2D_SCENE_CLIP_GROUP_POP: {
                if (stack.empty())
                    return false;
                const auto f = stack.back();
                stack.pop_back();
                if (f.key != SIZE_MAX) {
                    counts[f.key].live_target -= f.targets;
                    counts[f.key].live_plain -= f.plain;
                }
                width = f.width;
                height = f.height;
                matrix = *D2D1::Matrix3x2F::ReinterpretBaseType(&f.previous);
                blend = f.blend;
                break;
            }
            case SPDF_D2D_SCENE_COMPOSITE_PUSH:
            case SPDF_D2D_SCENE_CLIP_GROUP_PUSH:
            case SPDF_D2D_SCENE_COMPOSITE_MASK_BEGIN: {
                if (stack.size() >= 4096)
                    return false;
                Frame f;
                f.width = width;
                f.height = height;
                f.previous = matrix;
                f.blend = blend;
                Surface::Path *clip = nullptr;
                bool isolated = false;
                const bool mask = c.type == SPDF_D2D_SCENE_COMPOSITE_MASK_BEGIN;
                const bool nonisolated =
                    c.type == SPDF_D2D_SCENE_COMPOSITE_PUSH && (c.uint_values[1] & 2) != 0;
                const auto mode = c.type == SPDF_D2D_SCENE_COMPOSITE_PUSH ? c.uint_values[0] : 0;
                const bool knockout =
                    c.type == SPDF_D2D_SCENE_COMPOSITE_PUSH && (c.uint_values[1] & 1) != 0;
                if (c.type == SPDF_D2D_SCENE_CLIP_GROUP_PUSH) {
                    matrix = adjusted(c);
                    f.previous = matrix;
                    clip = scene->bindings[stored.binding_index].path.get();
                } else if (mask) {
                    matrix = adjusted(c);
                    f.previous = matrix;
                } else if (role & Scene::IsolatedClipOpen) {
                    const auto &child = scene->data->commands[index + 1];
                    auto *path = scene->bindings[child.binding_index].path.get();
                    auto m = adjusted(child.command);
                    auto inverse = m;
                    bool can =
                        path && inverse.Invert() && blend == D2D1_PRIMITIVE_BLEND_SOURCE_OVER;
                    for (const auto &p : stack)
                        if (p.building)
                            can = false;
                    if (can && path->rectangle &&
                        ((m._12 == 0 && m._21 == 0) || (m._11 == 0 && m._22 == 0))) {
                        D2D1_RECT_F b{};
                        if (SUCCEEDED(path->resource->GetBounds(&m, &b))) {
                            const auto guard = 2 * 96.0f / dpi;
                            if (b.left <= -guard && b.top <= -guard &&
                                b.right >= width * 96.0f / dpi + guard &&
                                b.bottom >= height * 96.0f / dpi + guard)
                                can = false;
                        }
                    }
                    if (can) {
                        isolated = true;
                        clip = path;
                        matrix = m;
                    }
                }
                bool passthrough = false;
                if (clip || mask) {
                    D2D1_RECT_F b{};
                    if (clip) {
                        if (FAILED(clip->resource->GetBounds(&matrix, &b)))
                            return false;
                    } else {
                        const auto point = [&](float x, float y) {
                            return D2D1::Point2F(x * matrix._11 + y * matrix._21 + matrix._31,
                                                 x * matrix._12 + y * matrix._22 + matrix._32);
                        };
                        const D2D1_POINT_2F p[] = {
                            point(c.values[0], c.values[1]), point(c.values[2], c.values[1]),
                            point(c.values[0], c.values[3]), point(c.values[2], c.values[3])};
                        b = D2D1::RectF(p[0].x, p[0].y, p[0].x, p[0].y);
                        for (const auto &v : p) {
                            b.left = (std::min)(b.left, v.x);
                            b.right = (std::max)(b.right, v.x);
                            b.top = (std::min)(b.top, v.y);
                            b.bottom = (std::max)(b.bottom, v.y);
                        }
                    }
                    const auto dw = width * 96.0f / dpi, dh = height * 96.0f / dpi,
                               guard = 2 * 96.0f / dpi;
                    if (clip && !isolated && clip->rectangle &&
                        ((matrix._12 == 0 && matrix._21 == 0) ||
                         (matrix._11 == 0 && matrix._22 == 0)) &&
                        b.left <= -guard && b.top <= -guard && b.right >= dw + guard &&
                        b.bottom >= dh + guard)
                        passthrough = true;
                    if (!passthrough) {
                        if (!std::isfinite(b.left) || !std::isfinite(b.top) ||
                            !std::isfinite(b.right) || !std::isfinite(b.bottom))
                            b = D2D1::RectF(0, 0, dw, dh);
                        const auto sx = static_cast<float>(width) / dw,
                                   sy = static_cast<float>(height) / dh;
                        auto l = (std::max)(0, static_cast<int>(std::floor(b.left * sx)) - 1),
                             t = (std::max)(0, static_cast<int>(std::floor(b.top * sy)) - 1);
                        auto r = (std::min)(static_cast<int>(width),
                                            static_cast<int>(std::ceil(b.right * sx)) + 1),
                             bot = (std::min)(static_cast<int>(height),
                                              static_cast<int>(std::ceil(b.bottom * sy)) + 1);
                        if (r <= l) {
                            l = b.left >= dw ? static_cast<int>(width) - 1 : 0;
                            r = l + 1;
                        }
                        if (bot <= t) {
                            t = b.top >= dh ? static_cast<int>(height) - 1 : 0;
                            bot = t + 1;
                        }
                        f.cropped = true;
                        f.origin = D2D1::Point2F(l / sx, t / sy);
                        width = static_cast<UINT32>(r - l);
                        height = static_cast<UINT32>(bot - t);
                        matrix._31 -= f.origin.x;
                        matrix._32 -= f.origin.y;
                    }
                }
                f.building = mask;
                f.isolated = isolated;
                if (!passthrough && (mode != 0 || clip || mask || nonisolated)) {
                    const UINT targets = mask ? 3 : (isolated ? 0 : (clip ? 2 : 1));
                    const UINT plain =
                        isolated || (nonisolated && (c.values[0] == 0 || c.values[0] == 1)) ? 0 : 1;
                    add(f, targets, plain);
                }
                stack.push_back(f);
                blend = knockout ? D2D1_PRIMITIVE_BLEND_COPY : D2D1_PRIMITIVE_BLEND_SOURCE_OVER;
                break;
            }
            default:
                break;
            }
        }
        if (!stack.empty())
            return false;
        std::vector<ScratchStorageNeed> needs;
        for (const auto &c : counts)
            if (c.uses > 1) {
                auto n = c.need;
                n.uses = c.uses;
                needs.push_back(n);
            }
        std::stable_sort(needs.begin(), needs.end(),
                         [](const ScratchStorageNeed &a, const ScratchStorageNeed &b) {
                             const auto ac = a.targets + a.plain, bc = b.targets + b.plain;
                             return static_cast<unsigned long long>(a.uses) * bc >
                                    static_cast<unsigned long long>(b.uses) * ac;
                         });
        return surface->prepare_storage(needs);
    } catch (...) {
        return false;
    }
}
