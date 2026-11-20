"""Os testes antigos do dashboard/scan assumem o carro de teste (Sentra B16, com leitura do câmbio).

O padrão do produto é o perfil genérico; aqui os testes que dependem do Sentra o pedem pelo ambiente.
Os testes de tests/test_profiles.py escolhem o perfil explicitamente.
"""
import os

os.environ.setdefault("NISSAN_SCANNER_PROFILE", "nissan-sentra-b16-2010")
