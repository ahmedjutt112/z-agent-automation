import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.zagent.automation',
  appName: 'AI Automation Agent',
  webDir: 'renderer/dist',
  bundledWebRuntime: false,
  backgroundColor: '#09090b',
  android: {
    allowMixedContent: false,
    captureInput: true,
    webContentsDebuggingEnabled: false,
  },
  server: {
    // For development: uncomment + set androidScheme to test against a dev server
    // androidScheme: 'http',
    // url: 'http://192.168.1.100:5173',
    cleartext: false,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 1500,
      backgroundColor: '#09090b',
      showSpinner: false,
      androidSplashResourceName: 'splash',
      androidScaleType: 'CENTER_CROP',
    },
    LocalNotifications: {
      smallIcon: 'ic_stat_icon',
      iconColor: '#09090b',
      sound: 'bell.wav',
    },
  },
};

export default config;
