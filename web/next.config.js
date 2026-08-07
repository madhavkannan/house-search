/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.propertyguru.com.sg" },
      { protocol: "https", hostname: "**.99.co" },
      { protocol: "https", hostname: "**.sgp1.digitaloceanspaces.com" },
    ],
  },
};

module.exports = nextConfig;
