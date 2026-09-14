import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.silvadigitaltech.youtubecreatoragent',
  appName: 'YouTube Creator Agent Elite',
  webDir: 'www',
  server: {
    url: 'https://creator.silvadigitaltech.com',
    androidScheme: 'https',
    cleartext: false
  },
  android: {
    allowMixedContent: false
  }
};

export default config;
