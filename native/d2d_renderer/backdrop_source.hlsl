#define D2D_INPUT_COUNT 3
#define D2D_INPUT0_SIMPLE
#define D2D_INPUT1_SIMPLE
#define D2D_INPUT2_SIMPLE
#include <d2d1effecthelpers.hlsli>

D2D_PS_ENTRY(main)
{
    float4 backdrop = D2DGetInput(0);
    float4 result = D2DGetInput(1);
    float alpha = saturate(D2DGetInput(2).a);
    // Remove the group's initial backdrop using independently rendered alpha.
    // Every input remains on the GPU; no color-based coverage guessing.
    return float4(clamp(result.rgb - backdrop.rgb * (1.0 - alpha), 0.0, alpha), alpha);
}
