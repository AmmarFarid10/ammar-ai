import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',workers:1,use:{baseURL:process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:8000',browserName:'chromium'},reporter:'list'});
