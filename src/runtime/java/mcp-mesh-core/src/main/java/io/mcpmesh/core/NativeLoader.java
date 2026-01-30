package io.mcpmesh.core;

import jnr.ffi.LibraryLoader;
import jnr.ffi.LibraryOption;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Locale;

/**
 * Platform-specific native library loader for MCP Mesh core.
 *
 * <p>This loader handles extracting and loading the native library from:
 * <ul>
 *   <li>Classpath resources (for JAR-bundled libraries)</li>
 *   <li>System library path (for development)</li>
 *   <li>Custom path via MESH_NATIVE_LIB_PATH environment variable</li>
 * </ul>
 */
public final class NativeLoader {

    private static final Logger log = LoggerFactory.getLogger(NativeLoader.class);
    private static final String LIB_NAME = "mcp_mesh_core";
    private static volatile MeshCore instance;
    private static volatile boolean loaded = false;

    private NativeLoader() {
        // Utility class
    }

    /**
     * Load and return the MeshCore native library interface.
     *
     * <p>This method is thread-safe and will only load the library once.
     *
     * @return The loaded MeshCore instance
     * @throws UnsatisfiedLinkError if the library cannot be loaded
     */
    public static synchronized MeshCore load() {
        if (instance != null) {
            return instance;
        }

        // Try custom path first
        String customPath = System.getenv("MESH_NATIVE_LIB_PATH");
        if (customPath != null && !customPath.isEmpty()) {
            log.info("Loading native library from custom path: {}", customPath);
            instance = loadFromPath(customPath);
            return instance;
        }

        // Try extracting from classpath resources
        try {
            Path extractedLib = extractFromClasspath();
            if (extractedLib != null) {
                log.info("Loading native library from extracted path: {}", extractedLib);
                instance = loadFromPath(extractedLib.getParent().toString());
                return instance;
            }
        } catch (IOException e) {
            log.debug("Could not extract library from classpath: {}", e.getMessage());
        }

        // Fall back to system library path
        log.info("Loading native library from system path");
        instance = LibraryLoader.create(MeshCore.class)
                .option(LibraryOption.LoadNow, true)
                .load(LIB_NAME);

        loaded = true;
        log.info("MCP Mesh native library loaded successfully, version: {}", instance.mesh_version());
        return instance;
    }

    /**
     * Check if the native library has been loaded.
     *
     * @return true if loaded, false otherwise
     */
    public static boolean isLoaded() {
        return loaded;
    }

    /**
     * Get the platform classifier for native library selection.
     *
     * @return Classifier like "osx-aarch_64", "linux-x86_64", etc.
     */
    public static String getPlatformClassifier() {
        String os = normalizeOs(System.getProperty("os.name"));
        String arch = normalizeArch(System.getProperty("os.arch"));
        return os + "-" + arch;
    }

    /**
     * Get the library file name for the current platform.
     *
     * @return Library file name like "libmcp_mesh_core.dylib" or "mcp_mesh_core.dll"
     */
    public static String getLibraryFileName() {
        String os = System.getProperty("os.name").toLowerCase(Locale.ROOT);
        if (os.contains("win")) {
            return LIB_NAME + ".dll";
        } else if (os.contains("mac")) {
            return "lib" + LIB_NAME + ".dylib";
        } else {
            return "lib" + LIB_NAME + ".so";
        }
    }

    private static MeshCore loadFromPath(String path) {
        return LibraryLoader.create(MeshCore.class)
                .option(LibraryOption.LoadNow, true)
                .search(path)
                .load(LIB_NAME);
    }

    private static Path extractFromClasspath() throws IOException {
        String classifier = getPlatformClassifier();
        String libFileName = getLibraryFileName();
        String resourcePath = "/META-INF/native/" + classifier + "/" + libFileName;

        log.debug("Looking for native library at classpath resource: {}", resourcePath);

        try (InputStream is = NativeLoader.class.getResourceAsStream(resourcePath)) {
            if (is == null) {
                log.debug("Native library not found in classpath: {}", resourcePath);
                return null;
            }

            // Create temp directory for extracted library
            Path tempDir = Files.createTempDirectory("mcp-mesh-native-");
            tempDir.toFile().deleteOnExit();

            Path libPath = tempDir.resolve(libFileName);
            Files.copy(is, libPath, StandardCopyOption.REPLACE_EXISTING);
            libPath.toFile().deleteOnExit();

            log.debug("Extracted native library to: {}", libPath);
            return libPath;
        }
    }

    private static String normalizeOs(String os) {
        os = os.toLowerCase(Locale.ROOT);
        if (os.contains("win")) {
            return "windows";
        } else if (os.contains("mac") || os.contains("darwin")) {
            return "osx";
        } else if (os.contains("linux")) {
            return "linux";
        } else {
            return os.replaceAll("\\s+", "_");
        }
    }

    private static String normalizeArch(String arch) {
        arch = arch.toLowerCase(Locale.ROOT);
        if (arch.equals("amd64") || arch.equals("x86_64")) {
            return "x86_64";
        } else if (arch.equals("aarch64") || arch.equals("arm64")) {
            return "aarch_64";
        } else if (arch.equals("x86") || arch.equals("i386") || arch.equals("i686")) {
            return "x86_32";
        } else {
            return arch;
        }
    }
}
