#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <dlfcn.h>
#endif

typedef struct { size_t ref_count; size_t len; char data[]; } encore_str_object;
typedef struct { encore_str_object *object; } encore_str;
extern void *encore_str_from_cstr(const char *value);

typedef void *VkInstance;
typedef void *VkPhysicalDevice;
typedef uint64_t VkSurfaceKHR;
typedef int32_t VkResult;
typedef void (*VkVoidFunction)(void);

enum {
    VK_SUCCESS = 0,
    VK_INCOMPLETE = 5,
    VK_STRUCTURE_TYPE_APPLICATION_INFO = 0,
    VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1,
    VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO = 2,
    VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO = 3,
    VK_STRUCTURE_TYPE_SUBMIT_INFO = 4,
    VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO = 5,
    VK_STRUCTURE_TYPE_FENCE_CREATE_INFO = 8,
    VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO = 9,
    VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO = 12,
    VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO = 14,
    VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO = 15,
    VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO = 16,
    VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO = 18,
    VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO = 19,
    VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO = 20,
    VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO = 22,
    VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO = 23,
    VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO = 24,
    VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO = 25,
    VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO = 26,
    VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO = 27,
    VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO = 28,
    VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO = 29,
    VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO = 30,
    VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO = 31,
    VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO = 32,
    VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO = 33,
    VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO = 34,
    VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET = 35,
    VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO = 37,
    VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO = 38,
    VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO = 39,
    VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO = 40,
    VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO = 42,
    VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO = 43,
    VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER = 45,
    VK_STRUCTURE_TYPE_MEMORY_BARRIER = 46,
    VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR = 1000001000,
    VK_STRUCTURE_TYPE_PRESENT_INFO_KHR = 1000001001,
    VK_PHYSICAL_DEVICE_TYPE_OTHER = 0,
    VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU = 1,
    VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU = 2,
    VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU = 3,
    VK_PHYSICAL_DEVICE_TYPE_CPU = 4,
    GRAPHENE_MAX_ADAPTERS = 16
};

enum {
    VK_SUBOPTIMAL_KHR = 1000001003,
    VK_ERROR_INCOMPATIBLE_DRIVER = -9,
    VK_ERROR_OUT_OF_DATE_KHR = -1000001004,
    VK_FORMAT_B8G8R8A8_UNORM = 44,
    VK_FORMAT_B8G8R8A8_SRGB = 50,
    VK_COLOR_SPACE_SRGB_NONLINEAR_KHR = 0,
    VK_PRESENT_MODE_FIFO_KHR = 2,
    VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR = 1,
    VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR = 1,
    VK_IMAGE_USAGE_TRANSFER_SRC_BIT = 1,
    VK_IMAGE_USAGE_TRANSFER_DST_BIT = 2,
    VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT = 16,
    VK_IMAGE_LAYOUT_PRESENT_SRC_KHR = 1000001002
};

enum {
    VK_SHADER_STAGE_VERTEX_BIT = 1,
    VK_SHADER_STAGE_FRAGMENT_BIT = 16,
    VK_SHADER_STAGE_COMPUTE_BIT = 32,
    VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST = 3,
    VK_POLYGON_MODE_FILL = 0,
    VK_CULL_MODE_NONE = 0,
    VK_CULL_MODE_FRONT_BIT = 1,
    VK_CULL_MODE_BACK_BIT = 2,
    VK_FRONT_FACE_COUNTER_CLOCKWISE = 0,
    VK_FRONT_FACE_CLOCKWISE = 1,
    VK_BLEND_FACTOR_ZERO = 0,
    VK_BLEND_FACTOR_ONE = 1,
    VK_BLEND_FACTOR_SRC_ALPHA = 6,
    VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA = 7,
    VK_BLEND_OP_ADD = 0,
    VK_SAMPLE_COUNT_1_BIT = 1,
    VK_COMPARE_OP_LESS = 1,
    VK_COLOR_COMPONENT_RGBA_BITS = 15,
    VK_ATTACHMENT_LOAD_OP_CLEAR = 1,
    VK_ATTACHMENT_STORE_OP_STORE = 0,
    VK_ATTACHMENT_LOAD_OP_DONT_CARE = 2,
    VK_ATTACHMENT_STORE_OP_DONT_CARE = 1,
    VK_PIPELINE_BIND_POINT_GRAPHICS = 0,
    VK_PIPELINE_BIND_POINT_COMPUTE = 1,
    VK_INDEX_TYPE_UINT32 = 1,
    VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER = 1,
    VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER = 6,
    VK_DESCRIPTOR_TYPE_STORAGE_BUFFER = 7,
    VK_SUBPASS_EXTERNAL = UINT32_MAX,
    VK_SUBPASS_CONTENTS_INLINE = 0
};

enum { VK_DYNAMIC_STATE_VIEWPORT = 0, VK_DYNAMIC_STATE_SCISSOR = 1 };
enum { VK_FILTER_LINEAR = 1, VK_SAMPLER_MIPMAP_MODE_LINEAR = 1, VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE = 2 };

enum {
    VK_IMAGE_LAYOUT_UNDEFINED = 0,
    VK_IMAGE_LAYOUT_GENERAL = 1,
    VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL = 2,
    VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL = 3,
    VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL = 5,
    VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL = 6,
    VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL = 7,
    VK_IMAGE_ASPECT_COLOR_BIT = 1,
    VK_IMAGE_ASPECT_DEPTH_BIT = 2,
    VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT = 1,
    VK_PIPELINE_STAGE_VERTEX_INPUT_BIT = 4,
    VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT = 256,
    VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT = 128,
    VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT = 2048,
    VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT = 1024,
    VK_PIPELINE_STAGE_TRANSFER_BIT = 4096,
    VK_PIPELINE_STAGE_HOST_BIT = 16384,
    VK_PIPELINE_STAGE_ALL_COMMANDS_BIT = 65536,
    VK_ACCESS_SHADER_READ_BIT = 32,
    VK_ACCESS_INDEX_READ_BIT = 2,
    VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT = 4,
    VK_ACCESS_SHADER_WRITE_BIT = 64,
    VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT = 256,
    VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT = 1024,
    VK_ACCESS_TRANSFER_READ_BIT = 2048,
    VK_ACCESS_TRANSFER_WRITE_BIT = 4096,
    VK_ACCESS_HOST_READ_BIT = 8192,
    VK_QUEUE_FAMILY_IGNORED = UINT32_MAX
};

enum {
    VK_QUEUE_GRAPHICS_BIT = 1,
    VK_QUEUE_COMPUTE_BIT = 2,
    VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT = 2,
    VK_COMMAND_BUFFER_LEVEL_PRIMARY = 0,
    VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT = 1,
    VK_FENCE_CREATE_SIGNALED_BIT = 1
};

enum {
    VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT = 1,
    VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT = 2,
    VK_MEMORY_PROPERTY_HOST_COHERENT_BIT = 4
};

typedef struct {
    uint32_t sType;
    const void *pNext;
    const char *pApplicationName;
    uint32_t applicationVersion;
    const char *pEngineName;
    uint32_t engineVersion;
    uint32_t apiVersion;
} VkApplicationInfo;

typedef struct {
    uint32_t sType;
    const void *pNext;
    uint32_t flags;
    const VkApplicationInfo *pApplicationInfo;
    uint32_t enabledLayerCount;
    const char *const *ppEnabledLayerNames;
    uint32_t enabledExtensionCount;
    const char *const *ppEnabledExtensionNames;
} VkInstanceCreateInfo;

typedef struct { char extensionName[256]; uint32_t specVersion; } VkExtensionProperties;
typedef struct { uint32_t queueFlags, queueCount, timestampValidBits; uint32_t granularity[3]; } VkQueueFamilyProperties;

typedef struct {
    uint32_t sType;
    const void *pNext;
    uint32_t flags;
    uint32_t queueFamilyIndex;
    uint32_t queueCount;
    const float *pQueuePriorities;
} VkDeviceQueueCreateInfo;

typedef struct {
    uint32_t sType;
    const void *pNext;
    uint32_t flags;
    uint32_t queueCreateInfoCount;
    const VkDeviceQueueCreateInfo *pQueueCreateInfos;
    uint32_t enabledLayerCount;
    const char *const *ppEnabledLayerNames;
    uint32_t enabledExtensionCount;
    const char *const *ppEnabledExtensionNames;
    const void *pEnabledFeatures;
} VkDeviceCreateInfo;

typedef struct {
    uint32_t sType;
    const void *pNext;
    uint32_t flags;
    uint32_t queueFamilyIndex;
} VkCommandPoolCreateInfo;

typedef struct {
    uint32_t sType;
    const void *pNext;
    void *commandPool;
    uint32_t level;
    uint32_t commandBufferCount;
} VkCommandBufferAllocateInfo;

typedef struct {
    uint32_t sType;
    const void *pNext;
    uint32_t flags;
    const void *pInheritanceInfo;
} VkCommandBufferBeginInfo;

typedef struct {
    uint32_t sType;
    const void *pNext;
    uint32_t waitSemaphoreCount;
    const void *pWaitSemaphores;
    const uint32_t *pWaitDstStageMask;
    uint32_t commandBufferCount;
    void *const *pCommandBuffers;
    uint32_t signalSemaphoreCount;
    const void *pSignalSemaphores;
} VkSubmitInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; } VkFenceCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; } VkSemaphoreCreateInfo;
typedef struct { uint32_t width, height; } VkExtent2D;
typedef struct {
    uint32_t minImageCount, maxImageCount;
    VkExtent2D currentExtent, minImageExtent, maxImageExtent;
    uint32_t maxImageArrayLayers, supportedTransforms, currentTransform;
    uint32_t supportedCompositeAlpha, supportedUsageFlags;
} VkSurfaceCapabilitiesKHR;
typedef struct { uint32_t format, colorSpace; } VkSurfaceFormatKHR;
typedef struct {
    uint32_t sType; const void *pNext; uint32_t flags; VkSurfaceKHR surface;
    uint32_t minImageCount, imageFormat, imageColorSpace; VkExtent2D imageExtent;
    uint32_t imageArrayLayers, imageUsage, imageSharingMode, queueFamilyIndexCount;
    const uint32_t *pQueueFamilyIndices; uint32_t preTransform, compositeAlpha, presentMode;
    uint32_t clipped; uint64_t oldSwapchain;
} VkSwapchainCreateInfoKHR;
typedef struct {
    uint32_t sType; const void *pNext; uint32_t waitSemaphoreCount; void *const *pWaitSemaphores;
    uint32_t swapchainCount; const uint64_t *pSwapchains; const uint32_t *pImageIndices; VkResult *pResults;
} VkPresentInfoKHR;
typedef union { float float32[4]; int32_t int32[4]; uint32_t uint32[4]; } VkClearColorValue;
typedef union { VkClearColorValue color; struct { float depth; uint32_t stencil; } depthStencil; } VkClearValue;
typedef struct { int32_t x, y; } VkOffset2D;
typedef struct { VkOffset2D offset; VkExtent2D extent; } VkRect2D;
typedef struct { float x, y, width, height, minDepth, maxDepth; } VkViewport;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; size_t codeSize; const uint32_t *pCode; } VkShaderModuleCreateInfo;
typedef struct {
    uint32_t sType; const void *pNext; uint32_t flags; uint32_t stage; void *module;
    const char *pName; const void *pSpecializationInfo;
} VkPipelineShaderStageCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t vertexBindingDescriptionCount; const void *pVertexBindingDescriptions; uint32_t vertexAttributeDescriptionCount; const void *pVertexAttributeDescriptions; } VkPipelineVertexInputStateCreateInfo;
typedef struct { uint32_t binding, stride, inputRate; } VkVertexInputBindingDescription;
typedef struct { uint32_t location, binding, format, offset; } VkVertexInputAttributeDescription;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t topology; uint32_t primitiveRestartEnable; } VkPipelineInputAssemblyStateCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t viewportCount; const VkViewport *pViewports; uint32_t scissorCount; const VkRect2D *pScissors; } VkPipelineViewportStateCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t depthClampEnable; uint32_t rasterizerDiscardEnable; uint32_t polygonMode; uint32_t cullMode; uint32_t frontFace; uint32_t depthBiasEnable; float depthBiasConstantFactor, depthBiasClamp, depthBiasSlopeFactor, lineWidth; } VkPipelineRasterizationStateCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t rasterizationSamples; uint32_t sampleShadingEnable; float minSampleShading; const uint32_t *pSampleMask; uint32_t alphaToCoverageEnable; uint32_t alphaToOneEnable; } VkPipelineMultisampleStateCreateInfo;
typedef struct { uint32_t failOp, passOp, depthFailOp, compareOp, compareMask, writeMask, reference; } VkStencilOpState;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t depthTestEnable, depthWriteEnable, depthCompareOp, depthBoundsTestEnable, stencilTestEnable; VkStencilOpState front, back; float minDepthBounds, maxDepthBounds; } VkPipelineDepthStencilStateCreateInfo;
typedef struct { uint32_t blendEnable; uint32_t srcColorBlendFactor, dstColorBlendFactor, colorBlendOp, srcAlphaBlendFactor, dstAlphaBlendFactor, alphaBlendOp, colorWriteMask; } VkPipelineColorBlendAttachmentState;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t logicOpEnable; uint32_t logicOp; uint32_t attachmentCount; const VkPipelineColorBlendAttachmentState *pAttachments; float blendConstants[4]; } VkPipelineColorBlendStateCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t dynamicStateCount; const uint32_t *pDynamicStates; } VkPipelineDynamicStateCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t setLayoutCount; const void *pSetLayouts; uint32_t pushConstantRangeCount; const void *pPushConstantRanges; } VkPipelineLayoutCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t magFilter, minFilter, mipmapMode; uint32_t addressModeU, addressModeV, addressModeW; float mipLodBias; uint32_t anisotropyEnable; float maxAnisotropy; uint32_t compareEnable, compareOp; float minLod, maxLod; uint32_t borderColor, unnormalizedCoordinates; } VkSamplerCreateInfo;
typedef struct { uint32_t binding, descriptorType, descriptorCount, stageFlags; const void *pImmutableSamplers; } VkDescriptorSetLayoutBinding;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t bindingCount; const VkDescriptorSetLayoutBinding *pBindings; } VkDescriptorSetLayoutCreateInfo;
typedef struct { uint32_t type, descriptorCount; } VkDescriptorPoolSize;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t maxSets, poolSizeCount; const VkDescriptorPoolSize *pPoolSizes; } VkDescriptorPoolCreateInfo;
typedef struct { uint32_t sType; const void *pNext; void *descriptorPool; uint32_t descriptorSetCount; void *const *pSetLayouts; } VkDescriptorSetAllocateInfo;
typedef struct { void *buffer; uint64_t offset, range; } VkDescriptorBufferInfo;
typedef struct { void *sampler; void *imageView; uint32_t imageLayout; } VkDescriptorImageInfo;
typedef struct { uint32_t sType; const void *pNext; void *dstSet; uint32_t dstBinding, dstArrayElement, descriptorCount, descriptorType; const void *pImageInfo; const VkDescriptorBufferInfo *pBufferInfo; const void *pTexelBufferView; } VkWriteDescriptorSet;
typedef struct { uint32_t flags, format, samples, loadOp, storeOp, stencilLoadOp, stencilStoreOp, initialLayout, finalLayout; } VkAttachmentDescription;
typedef struct { uint32_t attachment, layout; } VkAttachmentReference;
typedef struct { uint32_t flags, pipelineBindPoint, inputAttachmentCount; const VkAttachmentReference *pInputAttachments; uint32_t colorAttachmentCount; const VkAttachmentReference *pColorAttachments; const VkAttachmentReference *pResolveAttachments; const VkAttachmentReference *pDepthStencilAttachment; uint32_t preserveAttachmentCount; const uint32_t *pPreserveAttachments; } VkSubpassDescription;
typedef struct { uint32_t srcSubpass, dstSubpass, srcStageMask, dstStageMask, srcAccessMask, dstAccessMask, dependencyFlags; } VkSubpassDependency;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t attachmentCount; const VkAttachmentDescription *pAttachments; uint32_t subpassCount; const VkSubpassDescription *pSubpasses; uint32_t dependencyCount; const VkSubpassDependency *pDependencies; } VkRenderPassCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; void *renderPass; uint32_t attachmentCount; void *const *pAttachments; uint32_t width, height, layers; } VkFramebufferCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; uint32_t stageCount; const VkPipelineShaderStageCreateInfo *pStages; const VkPipelineVertexInputStateCreateInfo *pVertexInputState; const VkPipelineInputAssemblyStateCreateInfo *pInputAssemblyState; const void *pTessellationState; const VkPipelineViewportStateCreateInfo *pViewportState; const VkPipelineRasterizationStateCreateInfo *pRasterizationState; const VkPipelineMultisampleStateCreateInfo *pMultisampleState; const void *pDepthStencilState; const VkPipelineColorBlendStateCreateInfo *pColorBlendState; const void *pDynamicState; void *layout; void *renderPass; uint32_t subpass; void *basePipelineHandle; int32_t basePipelineIndex; } VkGraphicsPipelineCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t flags; VkPipelineShaderStageCreateInfo stage; void *layout; void *basePipelineHandle; int32_t basePipelineIndex; } VkComputePipelineCreateInfo;
typedef struct { uint32_t sType; const void *pNext; uint32_t srcAccessMask, dstAccessMask; } VkMemoryBarrier;
typedef struct { uint32_t sType; const void *pNext; void *renderPass; void *framebuffer; VkRect2D renderArea; uint32_t clearValueCount; const VkClearValue *pClearValues; } VkRenderPassBeginInfo;

typedef struct {
    uint32_t propertyFlags;
    uint32_t heapIndex;
} VkMemoryType;

typedef struct { uint64_t size; uint32_t flags; uint32_t padding; } VkMemoryHeap;
typedef struct {
    uint32_t memoryTypeCount;
    VkMemoryType memoryTypes[32];
    uint32_t memoryHeapCount;
    VkMemoryHeap memoryHeaps[16];
} VkPhysicalDeviceMemoryProperties;

typedef struct {
    uint32_t sType;
    const void *pNext;
    uint32_t flags;
    uint64_t size;
    uint32_t usage;
    uint32_t sharingMode;
    uint32_t queueFamilyIndexCount;
    const uint32_t *pQueueFamilyIndices;
} VkBufferCreateInfo;

typedef struct { uint64_t size, alignment; uint32_t memoryTypeBits; uint32_t padding; } VkMemoryRequirements;
typedef struct { uint32_t sType; const void *pNext; uint64_t allocationSize; uint32_t memoryTypeIndex; } VkMemoryAllocateInfo;

typedef struct { uint32_t width, height, depth; } VkExtent3D;
typedef struct {
    uint32_t sType;
    const void *pNext;
    uint32_t flags;
    uint32_t imageType;
    uint32_t format;
    VkExtent3D extent;
    uint32_t mipLevels;
    uint32_t arrayLayers;
    uint32_t samples;
    uint32_t tiling;
    uint32_t usage;
    uint32_t sharingMode;
    uint32_t queueFamilyIndexCount;
    const uint32_t *pQueueFamilyIndices;
    uint32_t initialLayout;
} VkImageCreateInfo;

typedef struct { uint32_t aspectMask, baseMipLevel, levelCount, baseArrayLayer, layerCount; } VkImageSubresourceRange;
typedef struct {
    uint32_t sType;
    const void *pNext;
    uint32_t flags;
    void *image;
    uint32_t viewType;
    uint32_t format;
    uint32_t components[4];
    VkImageSubresourceRange subresourceRange;
} VkImageViewCreateInfo;

typedef struct {
    uint32_t sType;
    const void *pNext;
    uint32_t srcAccessMask;
    uint32_t dstAccessMask;
    uint32_t oldLayout;
    uint32_t newLayout;
    uint32_t srcQueueFamilyIndex;
    uint32_t dstQueueFamilyIndex;
    void *image;
    VkImageSubresourceRange subresourceRange;
} VkImageMemoryBarrier;

typedef struct { uint32_t aspectMask, mipLevel, baseArrayLayer, layerCount; } VkImageSubresourceLayers;
typedef struct { int32_t x, y, z; } VkOffset3D;
typedef struct {
    uint64_t bufferOffset;
    uint32_t bufferRowLength;
    uint32_t bufferImageHeight;
    VkImageSubresourceLayers imageSubresource;
    VkOffset3D imageOffset;
    VkExtent3D imageExtent;
} VkBufferImageCopy;
typedef struct { uint64_t srcOffset, dstOffset, size; } VkBufferCopy;

typedef VkVoidFunction (*PFN_vkGetInstanceProcAddr)(VkInstance, const char *);
typedef VkResult (*PFN_vkEnumerateInstanceVersion)(uint32_t *);
typedef VkResult (*PFN_vkCreateInstance)(const VkInstanceCreateInfo *, const void *, VkInstance *);
typedef void (*PFN_vkDestroyInstance)(VkInstance, const void *);
typedef VkResult (*PFN_vkEnumeratePhysicalDevices)(VkInstance, uint32_t *, VkPhysicalDevice *);
typedef void (*PFN_vkGetPhysicalDeviceProperties)(VkPhysicalDevice, void *);
typedef VkResult (*PFN_vkEnumerateDeviceExtensionProperties)(VkPhysicalDevice, const char *, uint32_t *, VkExtensionProperties *);
typedef void (*PFN_vkGetPhysicalDeviceQueueFamilyProperties)(VkPhysicalDevice, uint32_t *, VkQueueFamilyProperties *);
typedef VkResult (*PFN_vkCreateDevice)(VkPhysicalDevice, const VkDeviceCreateInfo *, const void *, void **);
typedef VkVoidFunction (*PFN_vkGetDeviceProcAddr)(void *, const char *);
typedef void (*PFN_vkDestroyDevice)(void *, const void *);
typedef void (*PFN_vkGetDeviceQueue)(void *, uint32_t, uint32_t, void **);
typedef VkResult (*PFN_vkCreateCommandPool)(void *, const VkCommandPoolCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyCommandPool)(void *, void *, const void *);
typedef VkResult (*PFN_vkAllocateCommandBuffers)(void *, const VkCommandBufferAllocateInfo *, void **);
typedef void (*PFN_vkFreeCommandBuffers)(void *, void *, uint32_t, void *const *);
typedef VkResult (*PFN_vkBeginCommandBuffer)(void *, const VkCommandBufferBeginInfo *);
typedef VkResult (*PFN_vkEndCommandBuffer)(void *);
typedef VkResult (*PFN_vkResetCommandBuffer)(void *, uint32_t);
typedef VkResult (*PFN_vkQueueSubmit)(void *, uint32_t, const VkSubmitInfo *, void *);
typedef VkResult (*PFN_vkQueueWaitIdle)(void *);
typedef void (*PFN_vkGetPhysicalDeviceMemoryProperties)(VkPhysicalDevice, VkPhysicalDeviceMemoryProperties *);
typedef VkResult (*PFN_vkCreateBuffer)(void *, const VkBufferCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyBuffer)(void *, void *, const void *);
typedef void (*PFN_vkGetBufferMemoryRequirements)(void *, void *, VkMemoryRequirements *);
typedef VkResult (*PFN_vkAllocateMemory)(void *, const VkMemoryAllocateInfo *, const void *, void **);
typedef void (*PFN_vkFreeMemory)(void *, void *, const void *);
typedef VkResult (*PFN_vkBindBufferMemory)(void *, void *, void *, uint64_t);
typedef VkResult (*PFN_vkMapMemory)(void *, void *, uint64_t, uint64_t, uint32_t, void **);
typedef void (*PFN_vkUnmapMemory)(void *, void *);
typedef VkResult (*PFN_vkCreateImage)(void *, const VkImageCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyImage)(void *, void *, const void *);
typedef void (*PFN_vkGetImageMemoryRequirements)(void *, void *, VkMemoryRequirements *);
typedef VkResult (*PFN_vkBindImageMemory)(void *, void *, void *, uint64_t);
typedef VkResult (*PFN_vkCreateImageView)(void *, const VkImageViewCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyImageView)(void *, void *, const void *);
typedef void (*PFN_vkCmdPipelineBarrier)(void *, uint32_t, uint32_t, uint32_t, uint32_t, const void *, uint32_t, const void *, uint32_t, const VkImageMemoryBarrier *);
typedef void (*PFN_vkCmdCopyBufferToImage)(void *, void *, void *, uint32_t, uint32_t, const VkBufferImageCopy *);
typedef void (*PFN_vkCmdCopyImageToBuffer)(void *, void *, uint32_t, void *, uint32_t, const VkBufferImageCopy *);
typedef void (*PFN_vkCmdCopyBuffer)(void *, void *, void *, uint32_t, const VkBufferCopy *);
typedef VkResult (*PFN_vkCreateFence)(void *, const VkFenceCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyFence)(void *, void *, const void *);
typedef VkResult (*PFN_vkGetFenceStatus)(void *, void *);
typedef VkResult (*PFN_vkWaitForFences)(void *, uint32_t, void *const *, uint32_t, uint64_t);
typedef VkResult (*PFN_vkGetPhysicalDeviceSurfaceSupportKHR)(VkPhysicalDevice, uint32_t, VkSurfaceKHR, uint32_t *);
typedef VkResult (*PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR)(VkPhysicalDevice, VkSurfaceKHR, VkSurfaceCapabilitiesKHR *);
typedef VkResult (*PFN_vkGetPhysicalDeviceSurfaceFormatsKHR)(VkPhysicalDevice, VkSurfaceKHR, uint32_t *, VkSurfaceFormatKHR *);
typedef VkResult (*PFN_vkCreateSwapchainKHR)(void *, const VkSwapchainCreateInfoKHR *, const void *, uint64_t *);
typedef void (*PFN_vkDestroySwapchainKHR)(void *, uint64_t, const void *);
typedef VkResult (*PFN_vkGetSwapchainImagesKHR)(void *, uint64_t, uint32_t *, void **);
typedef VkResult (*PFN_vkAcquireNextImageKHR)(void *, uint64_t, uint64_t, void *, void *, uint32_t *);
typedef VkResult (*PFN_vkQueuePresentKHR)(void *, const VkPresentInfoKHR *);
typedef VkResult (*PFN_vkCreateSemaphore)(void *, const VkSemaphoreCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroySemaphore)(void *, void *, const void *);
typedef VkResult (*PFN_vkResetFences)(void *, uint32_t, void *const *);
typedef void (*PFN_vkCmdClearColorImage)(void *, void *, uint32_t, const VkClearColorValue *, uint32_t, const VkImageSubresourceRange *);
typedef VkResult (*PFN_vkCreateShaderModule)(void *, const VkShaderModuleCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyShaderModule)(void *, void *, const void *);
typedef VkResult (*PFN_vkCreateRenderPass)(void *, const VkRenderPassCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyRenderPass)(void *, void *, const void *);
typedef VkResult (*PFN_vkCreateFramebuffer)(void *, const VkFramebufferCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyFramebuffer)(void *, void *, const void *);
typedef VkResult (*PFN_vkCreatePipelineLayout)(void *, const VkPipelineLayoutCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyPipelineLayout)(void *, void *, const void *);
typedef VkResult (*PFN_vkCreateGraphicsPipelines)(void *, void *, uint32_t, const VkGraphicsPipelineCreateInfo *, const void *, void **);
typedef VkResult (*PFN_vkCreateComputePipelines)(void *, void *, uint32_t, const VkComputePipelineCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyPipeline)(void *, void *, const void *);
typedef void (*PFN_vkCmdBeginRenderPass)(void *, const VkRenderPassBeginInfo *, uint32_t);
typedef void (*PFN_vkCmdEndRenderPass)(void *);
typedef void (*PFN_vkCmdBindPipeline)(void *, uint32_t, void *);
typedef void (*PFN_vkCmdDraw)(void *, uint32_t, uint32_t, uint32_t, uint32_t);
typedef void (*PFN_vkCmdSetViewport)(void *, uint32_t, uint32_t, const VkViewport *);
typedef void (*PFN_vkCmdSetScissor)(void *, uint32_t, uint32_t, const VkRect2D *);
typedef void (*PFN_vkCmdBindVertexBuffers)(void *, uint32_t, uint32_t, void *const *, const uint64_t *);
typedef void (*PFN_vkCmdBindIndexBuffer)(void *, void *, uint64_t, uint32_t);
typedef void (*PFN_vkCmdDrawIndexed)(void *, uint32_t, uint32_t, uint32_t, int32_t, uint32_t);
typedef VkResult (*PFN_vkCreateDescriptorSetLayout)(void *, const VkDescriptorSetLayoutCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyDescriptorSetLayout)(void *, void *, const void *);
typedef VkResult (*PFN_vkCreateDescriptorPool)(void *, const VkDescriptorPoolCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroyDescriptorPool)(void *, void *, const void *);
typedef VkResult (*PFN_vkAllocateDescriptorSets)(void *, const VkDescriptorSetAllocateInfo *, void **);
typedef void (*PFN_vkUpdateDescriptorSets)(void *, uint32_t, const VkWriteDescriptorSet *, uint32_t, const void *);
typedef void (*PFN_vkCmdBindDescriptorSets)(void *, uint32_t, void *, uint32_t, uint32_t, void *const *, uint32_t, const uint32_t *);
typedef void (*PFN_vkCmdDispatch)(void *, uint32_t, uint32_t, uint32_t);
typedef VkResult (*PFN_vkCreateSampler)(void *, const VkSamplerCreateInfo *, const void *, void **);
typedef void (*PFN_vkDestroySampler)(void *, void *, const void *);

typedef struct {
    VkPhysicalDevice handle;
    char name[256];
    uint32_t api_version;
    uint32_t vendor_id;
    uint32_t device_id;
    uint32_t kind;
    uint32_t tier;
    bool ray_query;
    bool ray_pipeline;
    bool mesh_shader;
} GrapheneVkAdapter;

typedef struct {
    void *library;
    bool ready;
    bool (*Init)(uint32_t);
    void (*QuitSubSystem)(uint32_t);
    void *(*CreateWindow)(const char *, int, int, uint64_t);
    bool (*SyncWindow)(void *);
    bool (*GetWindowSizeInPixels)(void *, int *, int *);
    void (*DestroyWindow)(void *);
    bool (*PollEvent)(void *);
    const bool *(*GetKeyboardState)(int *);
    uint32_t (*GetMouseState)(float *, float *);
    bool (*VulkanLoadLibrary)(const char *);
    void (*VulkanUnloadLibrary)(void);
    const char *const *(*VulkanGetInstanceExtensions)(uint32_t *);
    bool (*VulkanCreateSurface)(void *, VkInstance, const void *, VkSurfaceKHR *);
    void (*VulkanDestroySurface)(VkInstance, VkSurfaceKHR, const void *);
    const char *(*GetError)(void);
} GrapheneSdlApi;

typedef struct {
    void *library;
    VkInstance instance;
    PFN_vkGetInstanceProcAddr get_proc;
    PFN_vkDestroyInstance destroy_instance;
    uint32_t api_version;
    GrapheneVkAdapter adapters[GRAPHENE_MAX_ADAPTERS];
    size_t adapter_count;
    bool available;
    bool window_support;
    bool owns_sdl_video;
    bool owns_sdl_vulkan;
    GrapheneSdlApi sdl;
    char error[256];
} GrapheneVkContext;

typedef union { uint32_t type; unsigned char padding[128]; } GrapheneSdlEvent;

typedef struct {
    GrapheneVkContext *owner;
    void *window;
    VkSurfaceKHR surface;
    uint32_t width;
    uint32_t height;
    bool keys[512];
    float mouse_x;
    float mouse_y;
    float mouse_dx;
    float mouse_dy;
    uint32_t mouse_buttons;
    bool mouse_initialized;
    bool open;
    bool owns_window;
    char error[256];
} GrapheneVkWindow;

typedef struct {
    GrapheneVkContext *context;
    VkPhysicalDevice physical_device;
    void *device;
    void *queue;
    void *command_pool;
    PFN_vkGetDeviceProcAddr get_device_proc;
    PFN_vkDestroyDevice destroy_device;
    PFN_vkDestroyCommandPool destroy_command_pool;
    PFN_vkAllocateCommandBuffers allocate_command_buffers;
    PFN_vkFreeCommandBuffers free_command_buffers;
    PFN_vkBeginCommandBuffer begin_command_buffer;
    PFN_vkEndCommandBuffer end_command_buffer;
    PFN_vkResetCommandBuffer reset_command_buffer;
    PFN_vkQueueSubmit queue_submit;
    PFN_vkQueueWaitIdle queue_wait_idle;
    PFN_vkCreateBuffer create_buffer;
    PFN_vkDestroyBuffer destroy_buffer;
    PFN_vkGetBufferMemoryRequirements get_buffer_requirements;
    PFN_vkAllocateMemory allocate_memory;
    PFN_vkFreeMemory free_memory;
    PFN_vkBindBufferMemory bind_buffer_memory;
    PFN_vkMapMemory map_memory;
    PFN_vkUnmapMemory unmap_memory;
    PFN_vkCreateImage create_image;
    PFN_vkDestroyImage destroy_image;
    PFN_vkGetImageMemoryRequirements get_image_requirements;
    PFN_vkBindImageMemory bind_image_memory;
    PFN_vkCreateImageView create_image_view;
    PFN_vkDestroyImageView destroy_image_view;
    PFN_vkCmdPipelineBarrier cmd_pipeline_barrier;
    PFN_vkCmdCopyBufferToImage cmd_copy_buffer_to_image;
    PFN_vkCmdCopyImageToBuffer cmd_copy_image_to_buffer;
    PFN_vkCmdCopyBuffer cmd_copy_buffer;
    PFN_vkCmdBindPipeline cmd_bind_pipeline;
    PFN_vkCmdBindDescriptorSets cmd_bind_descriptor_sets;
    PFN_vkCmdDispatch cmd_dispatch;
    PFN_vkCreateFence create_fence;
    PFN_vkDestroyFence destroy_fence;
    PFN_vkGetFenceStatus get_fence_status;
    PFN_vkWaitForFences wait_for_fences;
    VkPhysicalDeviceMemoryProperties memory_properties;
    uint32_t queue_family;
    uint32_t queue_flags;
    bool available;
    bool present;
    char error[256];
} GrapheneVkDevice;

typedef struct {
    GrapheneVkDevice *owner;
    void *command_buffer;
    bool recording;
    bool submitted;
    char error[256];
} GrapheneVkEncoder;

typedef struct {
    GrapheneVkDevice *owner;
    void *module;
    uint32_t stage;
    PFN_vkDestroyShaderModule destroy_shader_module;
    bool available;
    char error[256];
} GrapheneVkShader;

typedef struct {
    GrapheneVkDevice *owner;
    void *layout;
    uint32_t bindings[16];
    uint32_t types[16];
    uint32_t stages[16];
    uint32_t binding_count;
    PFN_vkDestroyDescriptorSetLayout destroy_layout;
    bool available;
    char error[256];
} GrapheneVkBindGroupLayout;

typedef struct {
    GrapheneVkDevice *owner;
    GrapheneVkBindGroupLayout *layout;
    void *pool;
    void *set;
    PFN_vkDestroyDescriptorPool destroy_pool;
    bool available;
    char error[256];
} GrapheneVkBindGroup;

typedef struct {
    GrapheneVkDevice *owner;
    void *sampler;
    PFN_vkDestroySampler destroy_sampler;
    bool available;
    char error[256];
} GrapheneVkSampler;

typedef struct {
    GrapheneVkDevice *owner;
    void *render_pass;
    void *layout;
    void *pipeline;
    uint32_t format;
    PFN_vkDestroyRenderPass destroy_render_pass;
    PFN_vkDestroyPipelineLayout destroy_pipeline_layout;
    PFN_vkDestroyPipeline destroy_pipeline;
    bool depth_test;
    bool available;
    char error[256];
} GrapheneVkPipeline;

typedef struct {
    GrapheneVkDevice *owner;
    void *layout;
    void *pipeline;
    PFN_vkDestroyPipelineLayout destroy_pipeline_layout;
    PFN_vkDestroyPipeline destroy_pipeline;
    bool available;
    char error[256];
} GrapheneVkComputePipeline;

typedef struct {
    GrapheneVkDevice *owner;
    void *buffer;
    void *memory;
    uint64_t size;
    uint32_t usage;
    bool host_visible;
    bool available;
    char error[256];
} GrapheneVkBuffer;

typedef struct {
    GrapheneVkDevice *owner;
    void *command_buffer;
    void *fence;
    bool complete;
    char error[256];
} GrapheneVkSubmission;

typedef struct {
    GrapheneVkDevice *owner;
    void *image;
    void *view;
    void *memory;
    uint32_t width;
    uint32_t height;
    uint32_t mip_levels;
    uint32_t format;
    uint32_t layout;
    uint32_t aspect;
    bool available;
    char error[256];
} GrapheneVkTexture;

typedef struct {
    GrapheneVkDevice *owner;
    GrapheneVkWindow *window;
    uint64_t swapchain;
    void **images;
    void **color_memories;
    void **views;
    void **depth_images;
    void **depth_views;
    void **depth_memories;
    void **framebuffers;
    uint32_t image_count;
    uint32_t format;
    uint32_t width;
    uint32_t height;
    void *command_buffers[2];
    void *image_available[2];
    void *render_finished[2];
    void *fences[2];
    uint32_t frame_index;
    PFN_vkDestroySwapchainKHR destroy_swapchain;
    PFN_vkAcquireNextImageKHR acquire_next_image;
    PFN_vkQueuePresentKHR queue_present;
    PFN_vkDestroySemaphore destroy_semaphore;
    PFN_vkResetFences reset_fences;
    PFN_vkCmdClearColorImage cmd_clear_color_image;
    PFN_vkDestroyImageView destroy_image_view;
    PFN_vkDestroyFramebuffer destroy_framebuffer;
    PFN_vkCmdBeginRenderPass cmd_begin_render_pass;
    PFN_vkCmdEndRenderPass cmd_end_render_pass;
    PFN_vkCmdBindPipeline cmd_bind_pipeline;
    PFN_vkCmdDraw cmd_draw;
    PFN_vkCmdSetViewport cmd_set_viewport;
    PFN_vkCmdSetScissor cmd_set_scissor;
    PFN_vkCmdBindVertexBuffers cmd_bind_vertex_buffers;
    PFN_vkCmdBindIndexBuffer cmd_bind_index_buffer;
    PFN_vkCmdDrawIndexed cmd_draw_indexed;
    PFN_vkCmdBindDescriptorSets cmd_bind_descriptor_sets;
    PFN_vkCreateFramebuffer create_framebuffer;
    void *active_render_pass;
    void *readback_buffer;
    void *readback_memory;
    void *readback_pixels;
    void *ui_staging_buffer;
    void *ui_staging_memory;
    void *ui_staging_pixels;
    uint32_t readback_pitch;
    bool frame_active;
    bool offscreen;
    bool available;
    char error[256];
} GrapheneVkSwapchain;

typedef struct {
    GrapheneVkSwapchain *owner;
    GrapheneVkPipeline *pipeline;
    void *command_buffer;
    uint32_t frame_index;
    uint32_t image_index;
    bool recording;
    bool in_render_pass;
    bool complete;
    char error[256];
} GrapheneVkFrame;

size_t graphene_vk_swapchain_create(size_t device_handle, size_t window_handle);
size_t graphene_vk_offscreen_create(size_t device_handle, uint32_t width, uint32_t height);
bool graphene_vk_swapchain_clear(size_t handle, float red, float green, float blue, float alpha);
bool graphene_vk_swapchain_destroy(size_t handle);
size_t graphene_vk_swapchain_pixels(size_t handle);
uint32_t graphene_vk_swapchain_pitch(size_t handle);
static uint32_t graphene_memory_type(GrapheneVkDevice *device, uint32_t allowed, uint32_t required);


/* Implementation fragments share this translation unit and its private Vulkan ABI. */
#include "platform.inc"
#include "device.inc"
#include "presentation.inc"
#include "resources.inc"
