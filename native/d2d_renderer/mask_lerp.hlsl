#define D2D_INPUT_COUNT 3
#define D2D_INPUT0_SIMPLE
#define D2D_INPUT1_SIMPLE
#define D2D_INPUT2_SIMPLE
#include <d2d1effecthelpers.hlsli>

D2D_PS_ENTRY(main)
{
    float4 backdrop = D2DGetInput(0);
    float4 source = D2DGetInput(1);
    float coverage = D2DGetInput(2).a;
    // Match the two UNORM8 intermediate composites in the original graph.
    float4 outside = floor(backdrop * (1.0 - coverage) * 255.0 + 0.5) / 255.0;
    float4 inside = floor(source * coverage * 255.0 + 0.5) / 255.0;
    return outside + inside;
}
