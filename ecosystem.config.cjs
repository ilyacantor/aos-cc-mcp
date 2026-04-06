module.exports = {
  apps: [
    {
      name: "aos-cc-mcp",
      script: "uv",
      args: "run python -m aos_cc_mcp.server",
      cwd: "/home/ilyac/code/aos-cc-mcp",
      autorestart: true,
      max_restarts: 10,
      restart_delay: 2000,
      env: {
        // Loaded from .env by python-dotenv at server startup.
        // pm2's env_file is not reliably supported across versions,
        // so the server handles .env loading itself.
      },
    },
  ],
};
