import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.vibeprompt.app",
  appName: "VibePrompt",
  webDir: "dist",
  server: {
    // Production APK loads bundled assets from webDir.
    // For live-reload against Vite during native debug, temporarily set:
    //   androidScheme: "https",
    //   url: "http://10.0.2.2:5173",
    androidScheme: "https",
  },
  android: {
    allowMixedContent: false,
  },
};

export default config;
