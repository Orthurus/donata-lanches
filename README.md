# DoNata Lanches

Sistema de comandas para lanchonete. O garçom lança os pedidos pelo **app Android**, e o **servidor no PC do caixa** recebe tudo pela rede local, imprime nos setores certos (cozinha, bar, chapa...) e fecha as contas.

## Como funciona

```
 Celular do garçom (app Android)  ──Wi‑Fi──►  PC do caixa (DoNata Servidor.exe)  ──►  impressoras
```

- O app **encontra o servidor sozinho** na rede (descoberta automática); se preferir, dá para digitar o IP do caixa.
- Tudo funciona na rede local, sem depender da internet. A internet só é usada para atualizar.

## Funcionalidades

**Painel do caixa (PC)**
- Mapa de mesas colorido (livre, em consumo, conta pedida), com adicionar e remover mesas.
- Lançamento de pedidos na mesa pelo caixa, abrindo mesa livre e escolhendo ou criando a comanda.
- Venda no balcão, com cardápio em abas e busca, carrinho e fechamento na hora.
- Formas de pagamento: Dinheiro, Débito, Crédito e Pix.
- Cardápio editável, com preço, categoria e local de preparo de cada produto.
- **Locais e impressoras:** crie os locais do seu negócio (Cozinha, Bar, Chapa, Sobremesas...), escolha a impressora de cada um, teste a impressão e ligue ou desligue a impressão automática.
- Usuários com PIN e perfis (administrador e garçom).
- Atualização automática do programa.

**App do garçom (Android)**
- Login por PIN, cardápio com busca e envio do pedido para o preparo.

## Instalação

Baixe os arquivos na aba [**Releases**](https://github.com/Orthurus/donata-lanches/releases) (versão mais recente):

| Arquivo | Onde instalar |
|---|---|
| `DoNata Servidor.exe` | No PC do caixa (Windows) |
| `donata.apk` | No celular Android do garçom (o painel do caixa também mostra um QR Code para baixar) |

O PC e os celulares precisam estar na **mesma rede Wi‑Fi**.

> **Importante:** o sistema vem com usuários de exemplo (Dono, Caixa e Garçom 1, com PINs simples). Troque os PINs antes de usar de verdade.

## Para desenvolver

Requisitos: Python 3.10 ou mais novo.

```
python donata_servidor.py     # servidor / painel do caixa (Tkinter)
python main.py                # app (Kivy), para testar no computador
```

| Arquivo | Função |
|---|---|
| `donata_servidor.py` | Servidor HTTP, painel do caixa, impressão e dados |
| `main.py` | App do garçom (Kivy) |
| `atualizador.py` | Atualização automática pelas Releases do GitHub |
| `buildozer.spec` | Configuração do APK Android |
| `.github/workflows/build.yml` | Gera o `.exe` e o `.apk` e anexa à Release |

## Publicando uma nova versão

1. Suba o número em `VERSAO` (`main.py`), em `VERSAO_SERVIDOR` (`donata_servidor.py`) e em `version` (`buildozer.spec`).
2. Crie uma Release com a tag `v` + versão (por exemplo, `v1.5`).
3. O GitHub Actions gera `DoNata Servidor.exe` e `donata.apk` e anexa à Release em alguns minutos.

A tag precisa ser igual à versão dentro do programa; caso contrário ele tenta se atualizar para a mesma versão em loop.

## Onde ficam os dados

O servidor guarda cardápio, usuários, mesas e vendas em `dados.json`, ao lado do programa. Faça cópias desse arquivo de vez em quando.

## Limitações conhecidas

- Não emite nota fiscal (NFC-e). Consulte o contador sobre a obrigatoriedade.
- Os dados ficam em um arquivo JSON, sem banco de dados.
