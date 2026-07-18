#version 450

layout(location = 0) in vec2 position;
layout(location = 1) in vec3 vertex_color;
layout(location = 0) out vec3 color;
layout(location = 1) out vec2 texture_coordinate;

layout(set = 0, binding = 0) uniform Transform {
    vec4 rotation_translation;
} transform;

void main() {
    float cosine = transform.rotation_translation.x;
    float sine = transform.rotation_translation.y;
    vec2 translated = mat2(cosine, -sine, sine, cosine) * position + transform.rotation_translation.zw;
    gl_Position = vec4(translated, 0.0, 1.0);
    color = vertex_color;
    texture_coordinate = position * 0.5 + 0.5;
}
