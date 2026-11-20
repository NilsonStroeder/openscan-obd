"""Gateway KWP/J2534 isolado do FastAPI.

O acesso à DLL J2534 é bloqueante. Este pacote concentra o transporte,
sessão KWP e polling para que a API asyncio nunca chame a DLL no event loop.
"""
