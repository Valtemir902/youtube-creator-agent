import type { CapacitorConfig } from '@capacitor/cli';

// Certified remote shell: HTTPS production only, no cleartext or mixed content.
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
