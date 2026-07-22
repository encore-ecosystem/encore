#version 450

layout(location = 0) in vec3 position;
layout(location = 1) in vec3 normal;
layout(location = 2) in vec3 vertex_color;
layout(location = 0) out vec3 world_normal;
layout(location = 1) out vec3 color;

layout(set = 0, binding = 0) uniform Camera {
    mat4 model_view_projection;
    mat4 model;
    vec4 light_direction;
    vec4 light_color_intensity;
    vec4 material_base_color;
    vec4 material_surface;
} camera;

void main() {
    gl_Position = camera.model_view_projection * vec4(position, 1.0);
    world_normal = normalize(mat3(camera.model) * normal);
    color = vertex_color;
}
