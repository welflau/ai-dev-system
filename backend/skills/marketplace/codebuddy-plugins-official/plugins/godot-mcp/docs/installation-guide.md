# Godot MCP Installation Guide

This guide walks you through installing and setting up the Godot MCP integration to use Claude with your Godot projects.

## Prerequisites

- Godot 4.x installed
- Node.js 18+ and npm installed
- Claude Desktop application

## Quick Install (Recommended)

The easiest way to set up Godot MCP is using the automated deployment tool:

```bash
# Clone the repository
git clone https://github.com/anengyuki/Godot-mcp.git
cd Godot-mcp

# Install dependencies and deploy
cd server
npm install
npm run deploy
```

The deploy script will automatically:
- Build the MCP server
- Detect your Claude Desktop config location (Windows/macOS/Linux)
- Add the `godot-mcp` configuration
- Display next steps

### Deploy Options

```bash
# Preview changes without writing
npm run deploy -- --dry-run

# Also copy the Godot addon to your project
npm run deploy -- --godot-project "/path/to/your/godot/project"

# Check deployment status
npm run status

# Diagnose connection issues
npm run status:diagnose

# Remove godot-mcp configuration
npm run uninstall
```

## Manual Installation

If you prefer manual setup:

## Manual Installation

If you prefer manual setup:

### 1. Install the Godot Addon

1. Copy the `godot_mcp` folder from the `addons` directory to your Godot project's `addons` folder
2. In your Godot project, go to "Project > Project Settings > Plugins"
3. Find the "Godot MCP" plugin and enable it
4. You should now see a "Godot MCP Server" panel in your editor's right dock

### 2. Build the MCP Server

1. Navigate to the `server` directory in your terminal
2. Install dependencies:
   ```bash
   npm install
   ```
3. Build the TypeScript code:
   ```bash
   npm run build
   ```

## Usage

### 1. Start the Godot WebSocket Server

1. Open your Godot project
2. In the "Godot MCP Server" panel, set the port (default: 9080)
3. Click "Start Server"
4. You should see a message confirming the server is running

### 2. Start the MCP Server

1. In the `server` directory, run:
   ```bash
   npm start
   ```
2. The server will automatically connect to the Godot WebSocket server

### 3. Connect Claude

1. In Claude desktop app, go to Settings > Developer
2. Enable Model Context Protocol
3. Add a new MCP tool with the following configuration:
   - Name: Godot MCP
   - Command: `node /path/to/godot-mcp/server/dist/index.js`
   - Working directory: `/path/to/your/project`
4. Save the configuration
5. When chatting with Claude, you can now access Godot tools

## Troubleshooting

For detailed troubleshooting steps, see the [Troubleshooting Guide](./troubleshooting-guide.md).

### Quick Checks

1. **Connection Issues**: Run `npm run status:diagnose` to test connectivity
2. **Configuration Issues**: Verify paths in Claude Desktop config are absolute
3. **Plugin Not Working**: Ensure the Godot MCP panel shows "Server Running"

### Common Solutions

- **Godot WebSocket not running**: Check the MCP panel in Godot editor
- **Port conflict**: The default port is 9080, ensure it's available
- **Path errors**: Always use forward slashes `/` in config paths