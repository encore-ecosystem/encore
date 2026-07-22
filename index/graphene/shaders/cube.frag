#version 450

layout(location = 0) in vec3 world_normal;
layout(location = 1) in vec3 color;
layout(location = 0) out vec4 output_color;

layout(set = 0, binding = 0) uniform Camera {
    mat4 model_view_projection;
    mat4 model;
    vec4 light_direction;
    vec4 light_color_intensity;
    vec4 material_base_color;
    vec4 material_surface;
} camera;

void main() {
    float diffuse = max(dot(normalize(world_normal), normalize(-camera.light_direction.xyz)), 0.0);
    float metallic = camera.material_surface.x;
    float roughness = camera.material_surface.y;
    float unlit = camera.material_surface.z;
    float diffuse_energy = (1.0 - metallic) * (1.0 - 0.25 * roughness);
    float illumination = 0.28 + diffuse * camera.light_color_intensity.w * diffuse_energy;
    vec3 base_color = color * camera.material_base_color.rgb;
    vec3 lit_color = base_color * camera.light_color_intensity.xyz * illumination;
    vec3 linear_color = mix(lit_color, base_color, unlit);
    output_color = vec4(pow(linear_color, vec3(1.0 / 2.2)), camera.material_base_color.a);
}
