@echo off
rem Wrapper para el MCP server anydesk.
rem El server detecta Tesseract con shutil.which("tesseract") y no lee
rem variables alternativas. Como el proceso Hermes puede heredar un PATH
rem viejo (explorer.exe que nunca refresco su entorno), este wrapper
rem setea la ruta explicitamente antes de lanzar el server.
set "PATH=%PATH%;C:\Program Files\Tesseract-OCR"
"C:\Users\juanp_8h8f07l\dev\mcp-anydesk\.venv\Scripts\python.exe" -m mcp_anydesk_server
