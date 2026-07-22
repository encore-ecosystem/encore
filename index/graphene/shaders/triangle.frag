#version 450

layout(location = 0) in vec3 color;
layout(location = 1) in vec2 texture_coordinate;
layout(location = 0) out vec4 output_color;

layout(set = 0, binding = 1) uniform sampler2D material_texture;

void main() {
    output_color = texture(material_texture, texture_coordinate) * vec4(color, 1.0);
}
