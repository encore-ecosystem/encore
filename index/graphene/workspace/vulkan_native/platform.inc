/* Loader, SDL window integration, instance and adapter discovery. */
static encore_str graphene_string(const char *value) {
    encore_str result = {(encore_str_object *)encore_str_from_cstr(value == NULL ? "" : value)};
    return result;
}

static bool graphene_vk_trace_enabled(void) { return getenv("GRAPHENE_VK_TRACE") != NULL; }

static char *graphene_c_string(encore_str value) {
    size_t length = value.object == NULL ? 0 : value.object->len;
    char *result = (char *)malloc(length + 1);
    if (result == NULL) return NULL;
    if (length > 0) memcpy(result, value.object->data, length);
    result[length] = '\0';
    return result;
}

static void graphene_error(GrapheneVkContext *context, const char *value) {
    if (context == NULL) return;
    const char *message = value == NULL ? "unknown Vulkan error" : value;
    size_t length = strlen(message);
    if (length >= sizeof(context->error)) length = sizeof(context->error) - 1;
    memcpy(context->error, message, length);
    context->error[length] = '\0';
}

static uint32_t graphene_vk_version(uint32_t major, uint32_t minor, uint32_t patch) {
    return (major << 22) | (minor << 12) | patch;
}

static void *graphene_open_vulkan(void) {
#if defined(_WIN32)
    return (void *)LoadLibraryA("vulkan-1.dll");
#elif defined(__APPLE__)
    const char *names[] = {"libvulkan.1.dylib", "libvulkan.dylib", "libMoltenVK.dylib", NULL};
    for (size_t i = 0; names[i] != NULL; ++i) {
        void *library = dlopen(names[i], RTLD_NOW | RTLD_LOCAL);
        if (library != NULL) return library;
    }
    return NULL;
#else
    void *library = dlopen("libvulkan.so.1", RTLD_NOW | RTLD_LOCAL);
    return library != NULL ? library : dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
#endif
}

static void *graphene_symbol(void *library, const char *name) {
#if defined(_WIN32)
    return (void *)GetProcAddress((HMODULE)library, name);
#else
    return dlsym(library, name);
#endif
}

static void graphene_close_vulkan(void *library) {
    if (library == NULL) return;
#if defined(_WIN32)
    FreeLibrary((HMODULE)library);
#else
    dlclose(library);
#endif
}

static bool graphene_load_sdl(GrapheneVkContext *context, bool initialize_video) {
#if defined(_WIN32)
    context->sdl.library = (void *)LoadLibraryA("SDL3.dll");
#elif defined(__APPLE__)
    const char *names[] = {"libSDL3.0.dylib", "libSDL3.dylib", "/opt/homebrew/lib/libSDL3.dylib", NULL};
    for (size_t i = 0; names[i] != NULL && context->sdl.library == NULL; ++i)
        context->sdl.library = dlopen(names[i], RTLD_NOW | RTLD_LOCAL);
#else
    context->sdl.library = dlopen("libSDL3.so.0", RTLD_NOW | RTLD_LOCAL);
    if (context->sdl.library == NULL) context->sdl.library = dlopen("libSDL3.so", RTLD_NOW | RTLD_LOCAL);
#endif
    if (context->sdl.library == NULL) { graphene_error(context, "SDL3 library was not found"); return false; }
#define GRAPHENE_SDL_LOAD(field, symbol) do { \
    context->sdl.field = (void *)graphene_symbol(context->sdl.library, symbol); \
    if (context->sdl.field == NULL) { graphene_error(context, "Required SDL3 Vulkan function was not found"); return false; } \
} while (0)
    GRAPHENE_SDL_LOAD(Init, "SDL_Init");
    GRAPHENE_SDL_LOAD(QuitSubSystem, "SDL_QuitSubSystem");
    GRAPHENE_SDL_LOAD(CreateWindow, "SDL_CreateWindow");
    GRAPHENE_SDL_LOAD(SyncWindow, "SDL_SyncWindow");
    GRAPHENE_SDL_LOAD(GetWindowSizeInPixels, "SDL_GetWindowSizeInPixels");
    GRAPHENE_SDL_LOAD(DestroyWindow, "SDL_DestroyWindow");
    GRAPHENE_SDL_LOAD(PollEvent, "SDL_PollEvent");
    GRAPHENE_SDL_LOAD(GetKeyboardState, "SDL_GetKeyboardState");
    GRAPHENE_SDL_LOAD(GetMouseState, "SDL_GetMouseState");
    GRAPHENE_SDL_LOAD(VulkanLoadLibrary, "SDL_Vulkan_LoadLibrary");
    GRAPHENE_SDL_LOAD(VulkanUnloadLibrary, "SDL_Vulkan_UnloadLibrary");
    GRAPHENE_SDL_LOAD(VulkanGetInstanceExtensions, "SDL_Vulkan_GetInstanceExtensions");
    GRAPHENE_SDL_LOAD(VulkanCreateSurface, "SDL_Vulkan_CreateSurface");
    GRAPHENE_SDL_LOAD(VulkanDestroySurface, "SDL_Vulkan_DestroySurface");
    GRAPHENE_SDL_LOAD(GetError, "SDL_GetError");
#undef GRAPHENE_SDL_LOAD
    if (initialize_video) {
        if (!context->sdl.Init(0x20u)) { graphene_error(context, context->sdl.GetError()); return false; }
        context->owns_sdl_video = true;
    }
    if (!context->sdl.VulkanLoadLibrary(NULL)) { graphene_error(context, context->sdl.GetError()); return false; }
    context->owns_sdl_vulkan = true;
    context->sdl.ready = true;
    return true;
}

static void graphene_unload_sdl(GrapheneVkContext *context) {
    if (context == NULL || context->sdl.library == NULL) return;
    if (context->sdl.ready) {
        if (context->owns_sdl_vulkan) context->sdl.VulkanUnloadLibrary();
        if (context->owns_sdl_video) context->sdl.QuitSubSystem(0x20u);
    }
#if defined(_WIN32)
    FreeLibrary((HMODULE)context->sdl.library);
#else
    dlclose(context->sdl.library);
#endif
    memset(&context->sdl, 0, sizeof(context->sdl));
}

static bool graphene_has_extension(VkPhysicalDevice device,
    PFN_vkEnumerateDeviceExtensionProperties enumerate_extensions, const char *name) {
    uint32_t count = 0;
    if (enumerate_extensions(device, NULL, &count, NULL) != VK_SUCCESS || count == 0) return false;
    VkExtensionProperties *properties = (VkExtensionProperties *)calloc(count, sizeof(VkExtensionProperties));
    if (properties == NULL) return false;
    VkResult result = enumerate_extensions(device, NULL, &count, properties);
    bool found = false;
    if (result == VK_SUCCESS || result == VK_INCOMPLETE) {
        for (uint32_t i = 0; i < count; ++i) {
            if (strcmp(properties[i].extensionName, name) == 0) { found = true; break; }
        }
    }
    free(properties);
    return found;
}

static void graphene_read_adapter(GrapheneVkAdapter *adapter, VkPhysicalDevice device,
    PFN_vkGetPhysicalDeviceProperties get_properties,
    PFN_vkEnumerateDeviceExtensionProperties enumerate_extensions) {
    unsigned char properties[1024];
    memset(properties, 0, sizeof(properties));
    get_properties(device, properties);
    adapter->handle = device;
    memcpy(&adapter->api_version, properties + 0, sizeof(uint32_t));
    memcpy(&adapter->vendor_id, properties + 8, sizeof(uint32_t));
    memcpy(&adapter->device_id, properties + 12, sizeof(uint32_t));
    memcpy(&adapter->kind, properties + 16, sizeof(uint32_t));
    memcpy(adapter->name, properties + 20, 255);
    adapter->name[255] = '\0';
    uint32_t major = adapter->api_version >> 22;
    uint32_t minor = (adapter->api_version >> 12) & 0x3ffu;
    adapter->tier = major > 1 || (major == 1 && minor >= 3) ? 1u : 0u;
    adapter->ray_query = graphene_has_extension(device, enumerate_extensions, "VK_KHR_ray_query") &&
        graphene_has_extension(device, enumerate_extensions, "VK_KHR_acceleration_structure");
    adapter->ray_pipeline = adapter->ray_query &&
        graphene_has_extension(device, enumerate_extensions, "VK_KHR_ray_tracing_pipeline");
    adapter->mesh_shader = graphene_has_extension(device, enumerate_extensions, "VK_EXT_mesh_shader");
    if (adapter->mesh_shader) adapter->tier = 2u;
    if (adapter->ray_query || adapter->ray_pipeline) adapter->tier = 3u;
}

size_t graphene_vk_create(bool debug, bool window_support, bool external_window) {
    (void)debug;
    GrapheneVkContext *context = (GrapheneVkContext *)calloc(1, sizeof(GrapheneVkContext));
    if (context == NULL) return 0;
    context->window_support = window_support;
    if (window_support && !graphene_load_sdl(context, !external_window)) return (size_t)context;
    context->library = graphene_open_vulkan();
    if (context->library == NULL) { graphene_error(context, "Vulkan loader was not found"); return (size_t)context; }
    context->get_proc = (PFN_vkGetInstanceProcAddr)graphene_symbol(context->library, "vkGetInstanceProcAddr");
    if (context->get_proc == NULL) { graphene_error(context, "vkGetInstanceProcAddr was not found"); return (size_t)context; }
    PFN_vkEnumerateInstanceVersion enumerate_version =
        (PFN_vkEnumerateInstanceVersion)context->get_proc(NULL, "vkEnumerateInstanceVersion");
    context->api_version = graphene_vk_version(1, 0, 0);
    if (enumerate_version != NULL) {
        uint32_t loader_version = graphene_vk_version(1, 0, 0);
        if (enumerate_version(&loader_version) == VK_SUCCESS) context->api_version = loader_version;
    }
    PFN_vkCreateInstance create_instance = (PFN_vkCreateInstance)context->get_proc(NULL, "vkCreateInstance");
    if (create_instance == NULL) { graphene_error(context, "vkCreateInstance was not found"); return (size_t)context; }
    uint32_t requested = context->api_version < graphene_vk_version(1, 3, 0)
        ? context->api_version : graphene_vk_version(1, 3, 0);
    VkApplicationInfo application = {
        VK_STRUCTURE_TYPE_APPLICATION_INFO, NULL, "Graphene", graphene_vk_version(0, 1, 0),
        "Graphene", graphene_vk_version(0, 1, 0), requested
    };
    uint32_t extension_count = 0;
    const char *const *extensions = NULL;
    if (window_support) {
        extensions = context->sdl.VulkanGetInstanceExtensions(&extension_count);
        if (extensions == NULL || extension_count == 0) {
            graphene_error(context, context->sdl.GetError()); return (size_t)context;
        }
    }
    VkInstanceCreateInfo create_info = {
        VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, NULL, 0, &application, 0, NULL, extension_count, extensions
    };
    VkResult result = create_instance(&create_info, NULL, &context->instance);
    if (result == VK_ERROR_INCOMPATIBLE_DRIVER && requested > graphene_vk_version(1, 0, 0)) {
        application.apiVersion = graphene_vk_version(1, 0, 0);
        context->api_version = application.apiVersion;
        result = create_instance(&create_info, NULL, &context->instance);
    }
    if (result != VK_SUCCESS) {
        snprintf(context->error, sizeof(context->error), "Unable to create Vulkan instance (result %d)", result);
        return (size_t)context;
    }
    context->destroy_instance = (PFN_vkDestroyInstance)context->get_proc(context->instance, "vkDestroyInstance");
    PFN_vkEnumeratePhysicalDevices enumerate_devices =
        (PFN_vkEnumeratePhysicalDevices)context->get_proc(context->instance, "vkEnumeratePhysicalDevices");
    PFN_vkGetPhysicalDeviceProperties get_properties =
        (PFN_vkGetPhysicalDeviceProperties)context->get_proc(context->instance, "vkGetPhysicalDeviceProperties");
    PFN_vkEnumerateDeviceExtensionProperties enumerate_extensions =
        (PFN_vkEnumerateDeviceExtensionProperties)context->get_proc(context->instance, "vkEnumerateDeviceExtensionProperties");
    if (enumerate_devices == NULL || get_properties == NULL || enumerate_extensions == NULL) {
        graphene_error(context, "Required Vulkan instance functions were not found"); return (size_t)context;
    }
    uint32_t count = 0;
    if (enumerate_devices(context->instance, &count, NULL) != VK_SUCCESS || count == 0) {
        graphene_error(context, "No Vulkan physical devices were found"); return (size_t)context;
    }
    if (count > GRAPHENE_MAX_ADAPTERS) count = GRAPHENE_MAX_ADAPTERS;
    VkPhysicalDevice devices[GRAPHENE_MAX_ADAPTERS];
    if (enumerate_devices(context->instance, &count, devices) != VK_SUCCESS) {
        graphene_error(context, "Unable to enumerate Vulkan physical devices"); return (size_t)context;
    }
    context->adapter_count = count;
    for (uint32_t i = 0; i < count; ++i) {
        graphene_read_adapter(&context->adapters[i], devices[i], get_properties, enumerate_extensions);
    }
    context->available = true;
    return (size_t)context;
}

bool graphene_vk_destroy(size_t handle) {
    GrapheneVkContext *context = (GrapheneVkContext *)handle;
    if (context == NULL) return false;
    if (context->instance != NULL && context->destroy_instance != NULL) context->destroy_instance(context->instance, NULL);
    graphene_close_vulkan(context->library);
    graphene_unload_sdl(context);
    free(context);
    return true;
}

static size_t graphene_vk_window_create_internal(size_t instance_handle, encore_str title,
    uint32_t width, uint32_t height) {
    GrapheneVkContext *context = (GrapheneVkContext *)instance_handle;
    GrapheneVkWindow *window = (GrapheneVkWindow *)calloc(1, sizeof(GrapheneVkWindow));
    if (window == NULL) return 0;
    window->owner = context;
    window->width = width;
    window->height = height;
    if (context == NULL || !context->available || !context->window_support || !context->sdl.ready || width == 0 || height == 0) {
        strncpy(window->error, "Vulkan instance was not created with window support", sizeof(window->error) - 1); return (size_t)window;
    }
    char *name = graphene_c_string(title);
    if (name == NULL) { strncpy(window->error, "Unable to allocate window title", sizeof(window->error) - 1); return (size_t)window; }
    window->window = context->sdl.CreateWindow(name, (int)width, (int)height,
        0x10000000ull | 0x2000ull | 0x20ull);
    window->owns_window = true;
    free(name);
    if (window->window == NULL) {
        strncpy(window->error, context->sdl.GetError(), sizeof(window->error) - 1); return (size_t)window;
    }
    if (!context->sdl.SyncWindow(window->window)) {
        strncpy(window->error, context->sdl.GetError(), sizeof(window->error) - 1); return (size_t)window;
    }
    int pixel_width = 0, pixel_height = 0;
    if (context->sdl.GetWindowSizeInPixels(window->window, &pixel_width, &pixel_height) && pixel_width > 0 && pixel_height > 0) {
        window->width = (uint32_t)pixel_width;
        window->height = (uint32_t)pixel_height;
    }
    if (!context->sdl.VulkanCreateSurface(window->window, context->instance, NULL, &window->surface)) {
        strncpy(window->error, context->sdl.GetError(), sizeof(window->error) - 1); return (size_t)window;
    }
    window->open = true;
    return (size_t)window;
}

size_t graphene_vk_window_create(size_t instance_handle, encore_str title, uint32_t width, uint32_t height) {
    return graphene_vk_window_create_internal(instance_handle, title, width, height);
}

size_t graphene_vk_window_attach(size_t instance_handle, size_t platform_handle, uint32_t width, uint32_t height) {
    GrapheneVkContext *context = (GrapheneVkContext *)instance_handle;
    GrapheneVkWindow *window = (GrapheneVkWindow *)calloc(1, sizeof(GrapheneVkWindow));
    if (window == NULL) return 0;
    window->owner = context;
    window->window = (void *)(uintptr_t)platform_handle;
    window->width = width;
    window->height = height;
    if (context == NULL || !context->available || !context->window_support || !context->sdl.ready ||
        window->window == NULL) {
        strncpy(window->error, "Invalid external SDL Vulkan window", sizeof(window->error) - 1);
        return (size_t)window;
    }
    int pixel_width = 0, pixel_height = 0;
    if (context->sdl.GetWindowSizeInPixels(window->window, &pixel_width, &pixel_height) &&
        pixel_width > 0 && pixel_height > 0) {
        window->width = (uint32_t)pixel_width;
        window->height = (uint32_t)pixel_height;
    }
    if (!context->sdl.VulkanCreateSurface(window->window, context->instance, NULL, &window->surface)) {
        strncpy(window->error, context->sdl.GetError(), sizeof(window->error) - 1);
        return (size_t)window;
    }
    window->open = true;
    return (size_t)window;
}

bool graphene_vk_window_available(size_t handle) { GrapheneVkWindow *w = (GrapheneVkWindow *)handle; return w != NULL && w->open && w->surface != 0; }
encore_str graphene_vk_window_error(size_t handle) { GrapheneVkWindow *w = (GrapheneVkWindow *)handle; return graphene_string(w == NULL ? "Invalid Graphene window" : w->error); }
bool graphene_vk_window_open(size_t handle) { GrapheneVkWindow *w = (GrapheneVkWindow *)handle; return w != NULL && w->open; }
uint32_t graphene_vk_window_width(size_t handle) { GrapheneVkWindow *w = (GrapheneVkWindow *)handle; return w == NULL ? 0 : w->width; }
uint32_t graphene_vk_window_height(size_t handle) { GrapheneVkWindow *w = (GrapheneVkWindow *)handle; return w == NULL ? 0 : w->height; }

bool graphene_vk_window_poll(size_t handle) {
    GrapheneVkWindow *window = (GrapheneVkWindow *)handle;
    if (window == NULL || !window->open || window->owner == NULL) return false;
    GrapheneSdlEvent event;
    while (window->owner->sdl.PollEvent(&event)) {
        if (event.type == 0x100u || event.type == 0x210u) window->open = false;
    }
    int key_count = 0;
    const bool *keys = window->owner->sdl.GetKeyboardState(&key_count);
    memset(window->keys, 0, sizeof(window->keys));
    if (keys != NULL && key_count > 0) {
        size_t copy_count = (size_t)key_count < sizeof(window->keys) ? (size_t)key_count : sizeof(window->keys);
        memcpy(window->keys, keys, copy_count);
    }
    float mouse_x = 0.0f, mouse_y = 0.0f;
    window->mouse_buttons = window->owner->sdl.GetMouseState(&mouse_x, &mouse_y);
    window->mouse_dx = window->mouse_initialized ? mouse_x - window->mouse_x : 0.0f;
    window->mouse_dy = window->mouse_initialized ? mouse_y - window->mouse_y : 0.0f;
    window->mouse_x = mouse_x; window->mouse_y = mouse_y; window->mouse_initialized = true;
    int pixel_width = 0, pixel_height = 0;
    if (window->owner->sdl.GetWindowSizeInPixels(window->window, &pixel_width, &pixel_height) &&
        pixel_width > 0 && pixel_height > 0) {
        window->width = (uint32_t)pixel_width;
        window->height = (uint32_t)pixel_height;
    }
    return window->open;
}

static void graphene_vk_window_refresh(GrapheneVkWindow *window) {
    if (window == NULL || window->owner == NULL || window->window == NULL) return;
    int pixel_width = 0, pixel_height = 0;
    if (window->owner->sdl.GetWindowSizeInPixels(window->window, &pixel_width, &pixel_height) &&
        pixel_width > 0 && pixel_height > 0) {
        window->width = (uint32_t)pixel_width;
        window->height = (uint32_t)pixel_height;
    }
}

bool graphene_vk_window_key_down(size_t handle, uint32_t scancode) {
    GrapheneVkWindow *window = (GrapheneVkWindow *)handle;
    return window != NULL && scancode < 512 && window->keys[scancode];
}
float graphene_vk_window_mouse_x(size_t handle) { GrapheneVkWindow *w = (GrapheneVkWindow *)handle; return w == NULL ? 0.0f : w->mouse_x; }
float graphene_vk_window_mouse_y(size_t handle) { GrapheneVkWindow *w = (GrapheneVkWindow *)handle; return w == NULL ? 0.0f : w->mouse_y; }
float graphene_vk_window_mouse_dx(size_t handle) { GrapheneVkWindow *w = (GrapheneVkWindow *)handle; return w == NULL ? 0.0f : w->mouse_dx; }
float graphene_vk_window_mouse_dy(size_t handle) { GrapheneVkWindow *w = (GrapheneVkWindow *)handle; return w == NULL ? 0.0f : w->mouse_dy; }
bool graphene_vk_window_mouse_down(size_t handle, uint32_t button_mask) {
    GrapheneVkWindow *window = (GrapheneVkWindow *)handle;
    return window != NULL && (window->mouse_buttons & button_mask) != 0;
}

bool graphene_vk_window_destroy(size_t handle) {
    GrapheneVkWindow *window = (GrapheneVkWindow *)handle;
    if (window == NULL) return false;
    if (window->owner != NULL && window->owner->sdl.ready) {
        if (window->surface != 0 && window->owner->instance != NULL)
            window->owner->sdl.VulkanDestroySurface(window->owner->instance, window->surface, NULL);
        if (window->owns_window && window->window != NULL) window->owner->sdl.DestroyWindow(window->window);
    }
    free(window);
    return true;
}

static GrapheneVkAdapter *graphene_adapter(size_t handle, size_t index) {
    GrapheneVkContext *context = (GrapheneVkContext *)handle;
    return context != NULL && index < context->adapter_count ? &context->adapters[index] : NULL;
}

bool graphene_vk_available(size_t handle) { GrapheneVkContext *c = (GrapheneVkContext *)handle; return c != NULL && c->available; }
encore_str graphene_vk_error(size_t handle) { GrapheneVkContext *c = (GrapheneVkContext *)handle; return graphene_string(c == NULL ? "Invalid Vulkan context" : c->error); }
uint32_t graphene_vk_api_version(size_t handle) { GrapheneVkContext *c = (GrapheneVkContext *)handle; return c == NULL ? 0 : c->api_version; }
size_t graphene_vk_adapter_count(size_t handle) { GrapheneVkContext *c = (GrapheneVkContext *)handle; return c == NULL ? 0 : c->adapter_count; }
encore_str graphene_vk_adapter_name(size_t h, size_t i) { GrapheneVkAdapter *a = graphene_adapter(h, i); return graphene_string(a == NULL ? "" : a->name); }
uint32_t graphene_vk_adapter_vendor(size_t h, size_t i) { GrapheneVkAdapter *a = graphene_adapter(h, i); return a == NULL ? 0 : a->vendor_id; }
uint32_t graphene_vk_adapter_device(size_t h, size_t i) { GrapheneVkAdapter *a = graphene_adapter(h, i); return a == NULL ? 0 : a->device_id; }
uint32_t graphene_vk_adapter_kind(size_t h, size_t i) { GrapheneVkAdapter *a = graphene_adapter(h, i); return a == NULL ? 0 : a->kind; }
uint32_t graphene_vk_adapter_api_version(size_t h, size_t i) { GrapheneVkAdapter *a = graphene_adapter(h, i); return a == NULL ? 0 : a->api_version; }
uint32_t graphene_vk_adapter_tier(size_t h, size_t i) { GrapheneVkAdapter *a = graphene_adapter(h, i); return a == NULL ? 0 : a->tier; }
bool graphene_vk_adapter_ray_query(size_t h, size_t i) { GrapheneVkAdapter *a = graphene_adapter(h, i); return a != NULL && a->ray_query; }
bool graphene_vk_adapter_ray_pipeline(size_t h, size_t i) { GrapheneVkAdapter *a = graphene_adapter(h, i); return a != NULL && a->ray_pipeline; }
bool graphene_vk_adapter_mesh_shader(size_t h, size_t i) { GrapheneVkAdapter *a = graphene_adapter(h, i); return a != NULL && a->mesh_shader; }
