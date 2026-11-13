# 4. Interface no PC – SOI Controller

Arquivo: [`interface/soi_controller.py`](../interface/soi_controller.py). Feito em PyQt/PySide + pyqtgraph. O lock-in é calculado em Python (numpy/scipy), no próprio arquivo.

## Instalação e execução

```powershell
pip install -r requirements.txt
python interface/soi_controller.py
```

**Executável para Windows**. Cada [Release](https://github.com/mbelancon/SOI/releases) traz o executável pronto, sem precisar instalar Python:

- `SOI_Controller_vX.Y.Z.exe`: arquivo único. Basta baixar e abrir. A cada abertura ele se descompacta numa pasta temporária, por isso leva alguns segundos para aparecer.
- `SOI_Controller_vX.Y.Z_pasta.zip`: a mesma interface em pasta. Descompacte e abra `SOI_Controller.exe`. Abre mais rápido.

Nos dois casos a pasta `Medidas/` é criada ao lado do `.exe`. Como o executável não é assinado, o Windows SmartScreen pode avisar na primeira vez: clique em "Mais informações" e "Executar assim mesmo".

**Processador necessário.** O executável e as versões atuais do numpy (2.4 ou mais nova) e do Qt (6.10 ou mais nova) exigem um processador x86-64 com as instruções SSSE3, SSE4.1, SSE4.2 e POPCNT, o nível chamado x86-64-v2. Qualquer Intel desde 2009 (Core i3/i5/i7 de 1ª geração em diante) ou AMD desde 2011 (FX/Bulldozer, Ryzen) atende. Em processadores mais antigos, como AMD Phenom II/Athlon II e Intel Core 2, o programa não abre e mostra:

```
ImportError: DLL load failed while importing _multiarray_umath: Uma rotina de inicialização da biblioteca de vínculo dinâmico (DLL) falhou.
```

Instalar driver ou o Visual C++ não resolve, porque faltam instruções no próprio processador. Nesses PCs é possível rodar com bibliotecas mais antigas (por exemplo, numpy 2.3 e PyQt5 5.15), mas num teste com um Phenom II o computador não deu conta da taxa de dados do INMP441, e o sinal ficou cortado. Use um PC mais novo.

O executável é gerado pelo GitHub Actions ([`.github/workflows/executavel-windows.yml`](../.github/workflows/executavel-windows.yml)) sempre que uma Release é publicada, e também pode ser gerado à mão na aba Actions. Para gerar localmente no Windows, num venv limpo:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r packaging/requirements-build.txt
.venv\Scripts\pyinstaller packaging/soi_controller.spec             # arquivo único em dist/
.venv\Scripts\pyinstaller packaging/soi_controller.spec -- --onedir # pasta em dist/SOI_Controller/
```

O spec ([`packaging/soi_controller.spec`](../packaging/soi_controller.spec)) deixa de fora os módulos não usados do Qt, as traduções e o OpenGL por software. Não usa o [UPX](https://upx.github.io/): com ele o executável fica uns 14 MB menor, mas o Controle Inteligente de Aplicativos do Windows 11 bloqueia as DLLs comprimidas e a interface não abre (`-- --upx` liga, para testes).

## Conexão com o STM32

- A porta é **detectada sozinha**. A ordem é: a variável de ambiente `TL_ARDUINO_PORT` (ex.: `COM7`), se existir; depois um dispositivo USB com VID `0x0483` (STM32); depois outras placas Arduino conhecidas; por fim, a única porta USB presente.
- Se a conexão cair, a interface **tenta reconectar a cada 3 s** e reenvia a frequência e o PWM atuais.
- A leitura serial roda numa thread separada: nenhum byte se perde se a interface atrasar.
- **Verificação da modulação:** o PLL do OPT101 trava nas bordas reais do laser. Se ele ficar destravado por mais de max(5 s, 5 períodos), o STM32 está modulando em outra frequência: o `F` se perdeu, ou a placa reiniciou no padrão de 5 Hz. Nesse caso a interface reenvia a frequência sozinha e avisa na barra de status. Isso protege principalmente o lock-in do INMP441, que não tem PLL e depende de a frequência do STM32 ser a mesma do campo. Enquanto o PLL está destravado, o status da aba OPT101 mostra **"PLL destravado"**.
- **Sem suspensão durante medidas (Windows):** enquanto uma varredura (OPT101, INMP441 ou Modo Duplo) ou o Teste de resolução estiver rodando, a interface impede o Windows de suspender ou hibernar por inatividade, e libera de novo no fim. A tela ainda pode apagar. Fechar a tampa do notebook, ou suspender pelo menu ou pelo botão, continua interrompendo a medida.
- **Sem STM32**, aparece a opção **"Simular amostragem"**, que gera sinais simulados do OPT101 e do INMP441 para testar a interface.
- As preferências (campos, opções, tamanho da janela, aba ativa) ficam salvas ao fechar, no registro do Windows (`HKCU\Software\LCTM\SOI Controller`). Não são salvas se uma varredura estiver em andamento.

## Barra de excitação (comum às abas)

| Controle | Faixa | Função |
|---|---|---|
| Freq (Hz) | 0 – 5000 | Frequência da modulação do laser (0 = contínuo). Também atualiza os cortes automáticos dos filtros. |
| PWM (%) | 0 – 100 | Potência do laser |
| **Amostra** | texto | Prefixo de todos os arquivos salvos em `Medidas/`. Caracteres inválidos em nomes de arquivo viram `_`. Vazio = sem prefixo. Fica salvo entre sessões. |
| Calibração + Usar | lista | Calibração do microfone aplicada na varredura em frequência do Modo Duplo. Lista as calibrações da pasta `Medidas/` da mais recente para a mais antiga (pela data no nome), sem os trechos `CAL_` e `microfone_`; o nome completo, a referência e a célula aparecem na dica. Cada item começa com a célula em que foi feita (`[OPC]` ou `[Câmara]`) e com ⚠ se não foi verificada. A lista é relida ao abrir. Ao iniciar, a mais recente vem selecionada e com **Usar** marcado. |
| **Célula** | OPC / Câmara | Configuração da célula na medida: **OPC** (a amostra fecha a abertura; luz por fora, microfone do outro lado) ou **Câmara** (amostra dentro, iluminada por uma janela de vidro). A calibração só vale na configuração em que foi feita; se for de outra, aparece um aviso vermelho. Vai para o cabeçalho dos CSV do Modo Duplo (`# Celula = …`). Escolher uma referência de calibração ajusta a célula automaticamente. |
| Finalizar experimento | botão | Compacta em `Medidas/<amostra>_<data>.zip` todos os arquivos salvos na sessão (desde que a interface abriu ou desde o último clique) e a calibração em uso (CSV e PNG). Os originais continuam na pasta. Durante uma varredura, ele pede para terminá-la ou cancelá-la antes. |

## Aba OPT101

**Barra de status:** estado do sinal (*Sinal OK*, *Sinal baixo* com nível médio < 5 % do ADC, ou *SATURAÇÃO DO ADC*), o **%ADC** de pico (verde < 50 %, laranja até 70 %, vermelho acima), a **frequência real medida pelo PLL** e a taxa em uso (ex.: *12,5 kS/s (OSR 16)*). Se o USB perder amostras ópticas, aparece em vermelho *Perdas USB: N amostras*: a interface preenche a lacuna repetindo a última amostra, para o tempo e o PLL seguirem certos.

**Osciloscópio:** sinal bruto do ADC (0–16 380) e a referência do laser (verde tracejado), em tempo real.
- *Janela (s)*: de 0,005 a 30 s. Acima de 50 Hz a janela fica limitada a 50 ciclos ("Visualização reduzida").
- *Filtro 60 Hz*: notches em 60 Hz e harmônicos até 1,5 kHz (largura de 2 Hz). Os notches a menos de 5 Hz da modulação são omitidos.
- *Sobreamostragem*: ver abaixo. *Teste de resolução*: ver abaixo.
- O osciloscópio guarda no máximo 120 mil pontos. Com janela longa e taxa alta (ex.: 30 s a 200 kS/s), cada ponto desenhado é a média de vários, para a tela não travar. O lock-in, a FFT e o Valor Médio usam sempre todas as amostras.

### Sobreamostragem

O STM32 (firmware 2.0.0) envia todas as amostras do ADC, 12 bits a 200 kS/s, e a interface tira a média de **OSR** amostras seguidas antes do lock-in, do osciloscópio, da FFT e do Valor Médio. O OSR é escolhido no topo da aba e fica salvo nas preferências:

| OSR | Taxa | Janela da média | Uso típico |
|---|---|---|---|
| 1 | 200 kS/s | 5 µs | Ver bordas rápidas no osciloscópio e no Valor Médio |
| 2 / 4 / 8 | 100 / 50 / 25 kS/s | 10 / 20 / 40 µs | Modulação alta (kHz) |
| **16** (padrão) | **12,5 kS/s** | **80 µs** | O mesmo da versão 1.0.0 |
| 32 / 64 | 6,25 / 3,125 kS/s | 160 / 320 µs | Modulação baixa, menos carga no PC |

- A escala exibida é sempre 0–16 380 (média × 4), como na 1.0.0, qualquer que seja o OSR.
- O ruído branco cai com √OSR (+½ bit a cada dobra), mas isso só vale se houver ruído suficiente (dither) e enquanto o ruído for branco. O *Teste de resolução* mostra até onde isso acontece no seu sinal.
- Para o lock-in, a escolha quase não muda a sensibilidade: o ruído final depende da banda do τ, não do OSR. O OSR muda a taxa, a banda útil (FS/2) e o atraso da referência.
- A magnitude do lock-in é corrigida pela atenuação da média (ver *Correção da média* no fim desta página) e a fase pelo atraso da referência de cada OSR.
- Trocar o OSR reinicia o lock-in, o osciloscópio, a FFT e o Valor Médio. Durante uma varredura a troca é bloqueada.

### Teste de resolução

Mede se a sobreamostragem está entregando resolução de verdade. Deixe o sinal **estável** (laser desligado, PWM 0 %, ou luz constante), clique em **Teste de resolução** e em **Medir**. A interface grava as amostras cruas (0,5 a 20 s, padrão 4 s) e mostra:

1. **Ruído × N** em escala log-log: o ruído das médias de N amostras, em LSB do ADC de 12 bits, calculado pelo desvio de Allan (insensível a uma deriva lenta e linear), junto da reta ideal 1/√N. Enquanto os pontos seguem a reta, a média está ganhando resolução. Quando a curva achata ou sobe, dominam ruído 1/f, interferência ou deriva, e aumentar o OSR não adianta mais. O círculo vermelho marca o OSR em uso. Os valores de N acima de 64 mostram a tendência para médias mais longas, como as do lock-in.
2. **Tabela:** ruído, ganho em bits (medido e ideal) e **bits efetivos** = 12 − log₂(σ·√12), a resolução de um conversor ideal com o mesmo ruído.
3. **Histograma dos códigos crus:** se as amostras se espalham por ~1 LSB ou mais, há o dither que a média precisa. Se quase todas caem num ou dois códigos (σ < 0,3 LSB), a média converge para o código errado e **não há resolução nova**, mesmo que o ruído das médias pareça cair.
4. **Conclusão:** até que N o ganho segue o ideal (no máximo 0,25 bit abaixo) e um aviso se o laser estava modulando durante a medida.

*Salvar CSV e PNG* grava `Resolucao_<data>.csv` (N, kS/s, σ de Allan, σ comum, ideal, ganhos e bits efetivos) e a imagem da janela em `Medidas/`.

**Gráfico inferior, dois modos:**

1. **Lock-In:** magnitude (azul) e fase (vermelho) no tempo. São 50 pontos/s, e o gráfico mostra os últimos 200 (4 s).
   - *τ* (constante de tempo de cada polo do passa-baixas): as setas andam na sequência 1–3–10 (1 ms, 3 ms, 10 ms, 30 ms, 100 ms, 300 ms, 1 s, 3 s, 10 s, 30 s e 100 s), e um valor digitado no meio (ex.: 0,5 s ou 200 ms) também é aceito. Ao mudar a frequência, τ volta ao automático: ~3 períodos da modulação, arredondado para 0,3 s (acima de ~5,8 Hz), 1 s (~1,8 a 5,8 Hz) ou 3 s (abaixo disso). Ao lado aparecem, calculados do τ, o corte de −3 dB do filtro de 2 polos (0,644/(2πτ)), a banda equivalente de ruído ENBW = 1/(8τ) e a espera de 9τ usada nas varreduras.
   - *Passa-Altas* (Hz): automático ao mudar a frequência (2 % de f, limitado a 0,01–0,05 Hz) e editável à mão.
2. **Valor Médio:** forma de onda média do ADC sobre N pulsos (1–1000), sincronizada na borda de subida do laser.
   - ◀ / ▶ ajustam o pré-trigger em passos de 10 ms.
   - **Análise da curva** (com o gráfico pausado): ajuste de **1 ou 2 exponenciais** `y = y∞ + A1·e^(−t/τ1) [+ A2·e^(−t/τ2)]` no trecho *On* ou *Off*. O intervalo é escolhido com duas linhas verdes arrastáveis. **Fit** desenha o modelo com os parâmetros digitados; **Otimizar** faz mínimos quadrados a partir deles e mostra o R².

*Pausa* congela o gráfico. **Salvar** grava CSV + PNG do gráfico inferior em `Medidas/`.

**FFT** (caixa ao lado de *Salvar*): espectro do sinal bruto do ADC, numa coluna à direita, em dBFS.
- Padrão: zoom em torno da referência, com FFT de 4 s de histórico (resolução ≈ 0,25 Hz).
- *Espectro completo*: de 0 a 6,25 kHz, FFT de 4096 pontos (≈ 3,1 Hz).
- *Fit*: ajusta a amplitude do pico na frequência real da modulação com a forma exata de uma senoide na janela Hann e mostra A (em FS, dBFS e contagens do ADC), o SNR pico/piso e a resolução. Se o pico estiver abaixo do limiar de sinal baixo, o gráfico avisa em vez de mostrar o fit.
- *Clique e zoom* (nas duas FFTs, OPT101 e INMP441): um clique mostra a frequência e a magnitude do ponto mais próximo; a rodinha dá zoom, arrastar move, o duplo clique volta à escala automática e o botão direito apaga o marcador.

![Aba OPT101 com a FFT do ADC e o painel de varreduras aberto (modo simulado)](imagens/interface_opt101.png)

**Varreduras (botão *Varreduras ▸*, só no modo Lock-In):**
- *Varredura em frequência*: início, fim e passo (0,1–5000 Hz).
- *Varredura em PWM*: início, fim e passo (0–100 %), na frequência atual.
- Em cada ponto a varredura **espera max(1 s, 9τ) + 0,3 s** para o filtro estabilizar e depois **mede por max(1 s, 4τ)**. Mostra o tempo estimado, o tempo restante e uma barra de progresso. O mesmo botão cancela.
- Ao terminar ou ser cancelada, uma varredura em frequência (OPT101, INMP441 ou Modo Duplo) volta à frequência de antes, reenviando `F` ao STM32, e aos cortes de filtro de antes, inclusive os ajustados à mão.
- No fim abre uma janela com magnitude ± desvio-padrão e fase × variável. Os eixos podem ir para escala log, com **fit de lei de potência (A·xⁿ)** ou **linear**.

## Aba INMP441

Lock-in do microfone, com filtros **independentes** dos do OPT101. A referência é numérica: a fase vem do número de sequência da amostra I2S e do marcador de modulação, sem PLL.

**Status:** taxa de amostras recebidas e o aviso **"SINAL BAIXO"** quando o SNR cai abaixo do limiar.

**Exibição:**
- Gráficos ligáveis: **Lock-In**, **Ruído/SNR** e **FFT**.
- **R/θ ↔ X/Y**: magnitude e fase, ou componentes em fase e em quadratura.
- **Auto-fase**: zera a fase média do último 1 s (o sinal vai todo para X). *Offset (°)*: correção manual.
- **Varreduras ▸**: mostra as varreduras em frequência e PWM do INMP441, que funcionam como as do OPT101.

**Lock-in:** τ, Passa-Altas, Filtro 60 Hz e *Janela (s)* (1–60 s exibidos). São 20 pontos/s (blocos de 2400 amostras a 48 kHz).

**Ruído/SNR:** média e desvio-padrão da saída do lock-in numa janela móvel (a mesma janela do gráfico, até 30 s). O SNR é mostrado em dB. O *Alerta SNR < (dB)* tem padrão de 10 dB (sinal ≈ 3× o ruído). Use uma janela de pelo menos 10τ.

**FFT:**
- Padrão: zoom em torno da referência, com FFT de 4 s de histórico (resolução ≈ 0,25 Hz).
- *Espectro completo*: de 0 a 24 kHz, FFT de 4096 pontos (≈ 11,7 Hz), em dBFS.
- *Fit*: ajusta o pico perto da referência com a forma exata de uma senoide na janela Hann. Corrige a frequência e a amplitude mesmo quando o tom cai entre dois bins.

## Aba Modo Duplo

Mede os dois lock-ins **no mesmo passo**. O R do OPT101 (proporcional à intensidade óptica) serve de referência de potência para o R do INMP441 (sinal fotoacústico).

**Topo da aba:**
- **Calibração ▸** abre, acima dos gráficos, o quadro da calibração do microfone (referência, curva esperada, dicas de montagem, passos 1–5 e esquema da célula) e, à direita, a **varredura em frequência da calibração**. Abrir o painel, ou rodar essa varredura, liga o **Fitar padrão**. Fechado, o Fitar padrão não é aplicado.
- **Varreduras ▸** abre as varreduras de medida: uma **varredura em frequência** com parâmetros próprios (separados dos da calibração, para medir amostras sem desfazer a configuração da calibração) e a **varredura casada em PWM**.
- **Ajuste com modelos ▸**, ao lado, abre o quadro dos modelos físicos (ver abaixo).
- Os três painéis começam fechados e o estado fica salvo entre sessões.
- **Abrir varredura…** carrega qualquer CSV do Modo Duplo da pasta Medidas, em frequência ou casada em PWM, inclusive os de formato antigo. A varredura aparece como se tivesse acabado de rodar: dá para aplicar calibração, ajustar modelos, excluir pontos, usar Fitar padrão e gerar calibração.
- **Salvar de novo** com uma varredura aberta grava `<nome original>_editado_<hora>.csv`, registrando o arquivo de origem no cabeçalho.
- **Limitação:** a varredura aberta não traz os cortes de filtro usados em cada ponto, então a banda do canal óptico não aparece na linha "Luz (OPT101)".

**τ das varreduras em frequência** (calibração e medidas): não há escolha de "Medida". Elas sempre usam integração longa: durante a varredura, os dois passa-baixas passam a ter esse τ (os valores são restaurados no fim), e em cada ponto a varredura espera 9τ e faz a média por 1τ. O campo τ é o mesmo τ do INMP441: ele começa com o valor da aba INMP441, e mudar o τ em qualquer um dos três lugares (aba INMP441, varredura da calibração ou varredura de medidas) muda os outros. Trocar a frequência de excitação leva o τ do INMP441 ao valor automático, e as varreduras acompanham.

**Medida** da varredura casada em PWM:
- *Média no tempo (τ atual)*: usa os filtros atuais. Espera 9τ do lock-in mais lento e faz a média por 4τ.
- *Integração longa (τ da varredura)*: usa temporariamente o τ escolhido nos dois passa-baixas (os valores são restaurados no fim). Espera 9τ e faz a média por 1τ. Dá menos ruído por ponto, mas a varredura demora mais.

**Varreduras:**
1. **Casada em PWM**: gráfico INMP441 R × OPT101 R com **ajuste linear** e gráfico OPT101 R × PWM. Verifica a linearidade do sinal fotoacústico com a potência.
2. **Em frequência (normalizada pelo OPT101)**: espaçamento **logarítmico** (N pontos) ou **linear** (passo). Os gráficos mostram **S = R_INMP441 / R_OPT101** e **Δφ = φ_INMP441 − φ_OPT101** (desenrolada). **Arranjo dos gráficos** (botão direito sobre um gráfico → Arranjo dos gráficos): *lado a lado*, *empilhado* (eixo x compartilhado; a escala de frequência fica em cima no gráfico de cima e embaixo no de baixo, com o nome do eixo uma vez só, para os dois ficarem colados) ou *sobrepostos*, com S no eixo da esquerda e a fase no eixo da direita. Em todos os arranjos, o eixo de S é azul e o da fase é vermelho, nas cores das curvas. Nos sobrepostos, zoom, arraste e clique para excluir pontos agem no gráfico de S; a fase acompanha o eixo x e ajusta a escala sozinha. A escolha fica salva. A varredura casada em PWM fica sempre lado a lado, porque os eixos x são diferentes.

**Layout:** os painéis Calibração, Varreduras e Ajuste com modelos abrem acima dos gráficos, e os gráficos ocupam o resto da tela. Os resultados em texto (Fit padrão, Diagnóstico, calibração aplicada, Luz) aparecem num **quadro flutuante sobre os gráficos**: arraste-o pelo título para tirá-lo de cima dos dados, ou recolha-o com ▾. A posição fica salva. Os textos longos (verificação completa, causas prováveis, detalhes do Diagnóstico) ficam nas dicas, ao passar o mouse. Em telas estreitas, o painel Calibração ganha rolagem horizontal em vez de alargar a janela.

**Normalizar pelo OPT101** (marcada por padrão, só na varredura em frequência): desmarcada, os gráficos e os ajustes usam o R e a fase do INMP441 sozinhos, sem dividir pelo R do OPT101 nem descontar a fase dele. Serve para ver a resposta crua do microfone ou separar um efeito do laser de um efeito da célula. Sem normalização, a calibração do microfone e o "Fitar padrão" ficam desligados, porque foram definidos para o sinal normalizado. O CSV salvo continua com os dois canais brutos e registra no cabeçalho se a normalização estava ligada.

**Mostrar sinais de cada sensor:** abre uma segunda fileira de gráficos com o sinal de cada sensor separado: amplitude do INMP441 e do OPT101, cada uma dividida pela própria mediana na varredura (a legenda mostra essa mediana), e a fase de cada um, desenrolada. Assim dá para ver de qual sensor vem uma variação da curva normalizada (por exemplo, a ressonância aparece só no INMP441, e uma queda de potência do laser aparece nos dois). Na varredura em PWM, o eixo x é o PWM.

**Diagnóstico** (varredura em frequência): separa o que é sinal fotoacústico do que é fundo. Ajusta amplitude e fase juntas com o modelo

z(f) = e^(−2πi·f·td) · HP(f) · R(f) · [A·(f/100 Hz)^−n·e^(iα) + B·e^(iβ)]

em que o primeiro termo entre colchetes é o fotoacústico (lei de potência, fase constante) e o segundo é um fundo plano (amplitude e fase que não mudam com a frequência: luz espalhada chegando ao microfone, chiado do driver do laser coerente com a modulação, acoplamento elétrico). HP é o passa-alta do microfone, td o atraso do sistema e R a ressonância da célula (só entra se houver pico). O ajuste é feito com e sem o fundo, e o fundo só é aceito se melhorar o ajuste de verdade (critério BIC). O gráfico mostra, com legenda, o modelo (preto), a componente fotoacústica (vermelho tracejado) e o fundo plano, não fotoacústico (roxo tracejado). O "atraso do canal do microfone" é o atraso puro da cadeia do microfone em relação à do OPT101, quase todo do filtro digital do INMP441 (~0,35 ms a 48 kHz); não é o tempo de voo do som nem o atraso térmico da amostra (esse fica na fase da componente fotoacústica), e o atraso do driver/laser se cancela em Δφ. O texto abaixo é curto: n, fc, atraso, f₀ e Q e, se houver fundo, um aviso vermelho de onde ele domina, pedindo para verificar a montagem e não gerar calibração. Os detalhes (razão fundo/fotoacústico em várias frequências, diferença de fase, incertezas e resíduo) ficam na dica do texto e no CSV. Usa os mesmos pontos do ajuste (respeita exclusões, calibração e normalização) e vai para o cabeçalho do CSV em "Salvar de novo". Leva alguns segundos e não roda durante a varredura. Precisa de pelo menos 12 pontos cobrindo uma década.

**Refinar ressonância** (abaixo do botão da varredura em frequência da calibração): ajusta a ressonância da célula (oscilador amortecido + fundo, só acima de 250 Hz) na varredura atual ou numa varredura aberta e mede mais pontos, igualmente espaçados, dentro da largura do pico: f0 ± f0/(2Q) (entre 2 % e 25 % de f0). "Pontos novos" escolhe quantos (12 por padrão); pontos a menos de 0,5 % de um já medido são pulados. Usa a Medida e o τ do quadro. Os pontos novos entram em ordem de frequência na mesma varredura, os pontos excluídos continuam excluídos, e ao terminar o CSV é gravado de novo (arquivo novo) com todos os pontos e a linha `# Refino da ressonância: …` no cabeçalho.

**Excluir pontos do ajuste:** clique num ponto do gráfico da esquerda (magnitude) para tirá-lo do ajuste. Ele fica vazado e cinza, e o ajuste é refeito na hora; clique de novo para incluí-lo, ou use **Incluir todos**. Quando há pontos sobrepostos, vale o mais próximo do cursor. Os pontos excluídos aparecem listados abaixo do gráfico, no cabeçalho do CSV do Modo Duplo (os dados continuam completos) e, na calibração, com `Valido = 0` e uma linha no cabeçalho. Uma varredura nova começa sem exclusões.

**Salvar de novo:** o CSV e o PNG do Modo Duplo são gravados automaticamente no fim da varredura. Depois de excluir pontos, ligar o "Fitar padrão" ou trocar a calibração, use **Salvar de novo** para gravar arquivos novos com sufixo `_editado`. O cabeçalho deles traz o ajuste, as exclusões e a calibração atuais, mais o nome do arquivo original, que não é alterado.

**Ajuste com modelos** (painel recolhível, só na varredura em frequência). Ajusta a magnitude, a fase ou as duas com modelos de célula aberta (luz por fora, microfone atrás da amostra). Com x = √(f/f₁) e f₁ = α/(πL²):

| Modelo | S(f) ∝ | Resultado |
|---|---|---|
| Lei de potência | f⁻ⁿ (fase constante; só magnitude) | n |
| Duas leis de potência (com quebra) | f⁻ⁿ¹ abaixo de fb, f⁻ⁿ² acima (contínuas; só magnitude) | n₁, n₂, fb (linha pontilhada no gráfico) |
| Difusão térmica (placa, detecção traseira) | f⁻⁰·⁵ / [σL·sinh(σL)], σL = (1+i)x | f₁ |
| Flexão termoelástica (Perondi–Miranda) | f⁻¹·[(1 − 1/x) + i/x] | f₁ |
| Câmara: amostra opaca (RG) | f⁻¹, fase constante (célula fechada, amostra dentro) | resíduos (sem parâmetro de forma) |
| Câmara: transparente e termicamente grossa (RG) | f⁻¹·⁵, fase constante | resíduos (sem parâmetro de forma) |
| Ressonância da célula | A·e^{i(φ0 − 2πfτ)}·[f₀²/(f₀² − f² + i·f·f₀/Q) + b·e^{iβ}] | f₀, Q, largura f₀/Q, ganho do pico (dB) |

- **Constantes livres:** a amplitude e a fase de cada modelo são livres. Com a calibração aplicada (**Usar**), os dados corrigidos são a resposta da amostra (a curva teórica da referência de calibração já foi descontada), então o modelo descreve só a amostra. Sem calibração, o painel avisa que magnitude e fase incluem a resposta do microfone/célula e o atraso do sistema.
- **Espessura:** com a **Espessura L** informada, o painel calcula a difusividade térmica **α = π·f₁·L²**. A incerteza mostrada não inclui a de L, que entra em dobro.
- **Faixa:** a **Faixa: de … a … Hz** limita o ajuste à região onde o modelo vale. Os pontos excluídos com clique também ficam fora. A curva verde tracejada é desenhada só na faixa ajustada.
- **Arquivos:** o resultado vai para o cabeçalho do CSV do Modo Duplo (use **Salvar de novo** depois de ajustar).
- **Ti de 23/10:** a flexão ajustada pela fase deu f₁ ≈ 22–23 Hz (resíduo de ~11°). A difusão pura não descreve esse Ti.
- **Modelos de câmara (RG):** para amostras de teste dentro da câmara, como vidro, depois de calibrar. Uma amostra semitransparente fica entre f⁻¹ e f⁻¹·⁵.
- **Ressonância da célula:** sem **Faixa** (início/fim), o pico é achado sozinho (maior excesso sobre uma reta em log-log, janela de ±3 larguras). Com **Marcar pico (2 cliques)**, clique no gráfico da esquerda um pouco abaixo e um pouco acima do pico; os cliques preenchem a Faixa. O ajuste usa magnitude e fase juntas (ou só uma delas) e desenha o modelo nos dois gráficos, com uma linha vertical em f₀. Meça com **Usar** desmarcado: a calibração remove a ressonância da célula. Com menos de 10 pontos na janela aparece a sugestão de uma varredura linear em volta do pico (passo ≤ largura/5). Na célula nova de 10/11/2026, a varredura de 35 pontos deu f₀ ≈ 1,57 kHz e Q ≈ 6,5 (só 6 pontos na janela).

**Calibração do microfone, em 5 passos: uma referência gera a calibração e uma segunda referência, diferente, a confere.** As ferramentas ficam no painel recolhível **Calibração ▸**, no topo da aba, fechado por padrão. Com o painel fechado, "Fitar padrão" não é aplicado.

*Por que duas referências:* na câmara, a célula tem ressonância de Helmholtz (~1,4–1,6 kHz) e o canal do microfone não é plano, então a resposta do sistema entra na forma de S(f). Uma referência sozinha não separa "a amostra não segue f⁻ⁿ" de "o sistema não é plano": o ajuste f⁻ⁿ·H(f) de um passa-altas só mostra se a forma é simples. Em 10/11/2026, a fita preta e o Al pintado deram a mesma forma entre 70 e 700 Hz, subindo de ~200 Hz até a ressonância: era o sistema, não as amostras. Por isso a calibração é gerada sem exigir que a referência siga f⁻ⁿ sozinha, e a prova vem do passo 5: depois de corrigida, uma segunda referência de material diferente tem de dar f⁻ⁿ com fase constante.

**Referência.** A caixa **Referência** escolhe o padrão. Cada um tem uma curva teórica S ∝ f⁻ⁿ com fase constante e vale numa configuração da célula, que é escolhida automaticamente em **Célula** (linha superior). Ao lado da caixa ficam os parâmetros editáveis (espessura L e difusividade α, ou n na personalizada), uma linha com a curva esperada e, à direita, um **esquema da montagem** com dicas: a amostra fecha a célula (OPC) ou fica dentro, sob a janela de vidro, com a folga de ar indicada (câmara).

| Referência | Célula | Curva teórica | Parâmetros | Observações |
|---|---|---|---|---|
| Folha de Al fina (modo OPC) | OPC | f⁻¹·⁵, fase constante; vale para f ≪ f₁ = α/(πL²) | L = 12 µm, α = 0,97 cm²/s | f₁ ≈ 214 kHz. Aviso se a varredura passar de f₁/10. É a calibração das versões anteriores. |
| Al espesso dentro da câmara | Câmara | f⁻¹, fase constante (Rosencwaig–Gersho, opaca) | L, α (só informativos) | Mostra μ = √(α/πf) e a transição fina/grossa; f⁻¹ vale nos dois regimes. Sinal fraco: o Al reflete ~90 %. |
| Folha de Al fina dentro da câmara | Câmara | f⁻¹, fase constante (opaca, termicamente fina sobre apoio grosso) | L, α (só informativos) | Folha com o lado fosco para o laser, lisa e colada sobre papel, plástico ou fita dupla face no fundo da câmara. O sinal depende do contato com o apoio (sem rugas nem bolhas). Sinal fraco. |
| Al pintado de preto fosco (câmara) | Câmara | f⁻¹ acima de ~100 Hz | L, α (só informativos) | A tinta é uma camada isolante sobre o Al: abaixo de ~10–100 Hz (conforme a espessura) parte do calor vai para o Al e o sinal cai. Acima disso se comporta como a fita preta (em 10/11/2026 as duas curvas tiveram a mesma forma entre 70 e 700 Hz). |
| Negro de fumo (câmara) | Câmara | f⁻¹, fase constante | nenhum | **Recomendada para gerar a calibração.** Padrão clássico da fotoacústica. Fuligem de vela sobre um pedaço de lâmina de vidro (apoio isolante, não metal), em camada grossa (~0,1 mm, preta fosca e opaca contra a luz), na mesma altura das amostras. Frágil: não toque nem sopre. |
| Fita preta fosca (câmara) | Câmara | f⁻¹, fase constante | nenhum | Rápida de montar e com sinal alto. Boa para conferir a calibração do negro de fumo (passo 5), ou para gerar. Limite a Faixa a ~1 kHz. |
| Personalizada (lei de potência) | a escolhida em Célula | f⁻ⁿ, fase constante | n | Para outro padrão de expoente conhecido. |

Não servem como referência: **vidro e PVC** (o expoente depende da absorção no comprimento de onda do laser) e **folha de Al pintada de preto em OPC** (a tinta fica termicamente grossa acima de ~0,1 Hz e destrói o f⁻¹·⁵). Vidro e PVC servem como amostras de teste, com os modelos de câmara do Ajuste com modelos. Na câmara, deixe 2–3 mm de ar ou mais sobre a amostra (μ do ar a 5 Hz ≈ 1,2 mm); a janela de vidro também absorve um pouco, o que pesa mais com Al polido.

1. Escolha a referência e monte-a como no esquema. A varredura em frequência da calibração já abre com os valores recomendados (definidos em `CAL_SWEEP_*` no topo do script; não ficam salvos entre sessões):
   - 5 a 2440 Hz, 35 pontos logarítmicos;
   - integração longa com τ = 2 s (≈ 12 min; é o mesmo τ do INMP441, que também passa a 2 s ao abrir).

   Ajuste você mesmo: PWM de 100 % (o PWM sempre abre baixo, por segurança), Filtro 60 Hz igual nos dois lock-ins (de preferência desligado) e **Usar** da calibração desmarcado (a calibração nova precisa dos dados brutos). Os campos continuam editáveis. Confira o %ADC do OPT101 e rode a varredura em frequência. Esses valores mantêm todos os pontos a ≥ 4 Hz de qualquer múltiplo de 60 Hz e longe das frequências em que o período é um número inteiro de amostras do OPT101 (ex.: 2500 Hz). Nessas frequências, a grade de 80 µs deixa um erro de até ~2 % no R.
2. Marque **Fitar padrão**. O modelo é `S(f) = A·f⁻ⁿ·H(f)`, com H um passa-altas de 1ª ordem de corte fc (microfone/célula), e `Δφ(f) = φ0 + atan(fc/f) − 360°·f·td`. *Incluir fase* usa também a fase. Pontos com SNR baixo ou resíduo > 3σ ficam marcados com ✕ vermelho. **Faixa: de … até** limita o ajuste e a verificação do passo 5 (use de ~70–150 Hz, acima do ruído e da interferência de 13–15 Hz, até abaixo da ressonância); os pontos fora da faixa continuam na calibração. Uma curva cinza pontilhada mostra a teoria da referência (f⁻ⁿ com o fc ajustado) em toda a faixa.

   **Verificação do comportamento.** O n sai livre e é comparado com o esperado da referência (✓ ou ⚠). A interface também confere se a fase fica constante depois de descontar fc e td e se a faixa confiável tem pelo menos uma década. Se algo falhar (|n − n_esperado| > 0,15, fase variando mais de ±15° ou faixa curta), aparece em laranja "Forma diferente de f⁻ⁿ", com os números (detalhes e causas prováveis na dica). Isso é normal na câmara, porque a ressonância e o canal do microfone entram na forma: é exatamente o que a calibração corrige. Não impede guardar a calibração; quem decide se ela vale é o passo 5.

   **Luz (OPT101)**, linha abaixo dos painéis: mostra o R do OPT101 em baixa frequência, quanto ele muda até o fim da varredura e a banda aproximada do canal óptico (driver + laser + OPT101). É só informação: a normalização já desconta a variação da luz, o atraso do driver/laser é comum ao microfone e se cancela em Δφ, e a calibração do microfone absorve o polo do OPT101 enquanto o resistor de realimentação for o mesmo. **Nada aqui precisa ser calibrado no uso normal.** Se a varredura passar de metade da banda óptica, aparece um aviso laranja. Os números completos do ajuste (τ pela fase e pela amplitude, φ0, subida 10–90 %) ficam na dica da linha e no cabeçalho do CSV.

   **τ do sensor (correção, em "Avançado ▸" no painel de calibração):** só é necessário se você trocar o resistor de realimentação do OPT101 entre a calibração e a medida. Com um valor no campo, o OPT101 é corrigido pelo polo do sensor antes de calcular S e Δφ. A fase recebe `+ atan(2π·f·τ)` e a amplitude é multiplicada por `√(1 + (2π·f·τ)²)`. Assim, a calibração deixa de depender do resistor de realimentação. O valor vale para o resistor montado agora e fica salvo entre sessões. Ao trocar o resistor, troque o valor. 0 = sem correção.
   - **Medir…** compara a varredura em frequência atual com outra já salva (`DUPLO_freq_*.csv`). As duas precisam ter a mesma luz (mesmo PWM e alinhamento) e resistores que mudem o ganho pelo menos 1,3×.
   - Na diferença de fase, a cadeia digital e o driver/laser se cancelam. O polo do OPT101 é proporcional a R_eq, e a razão de R_eq vem da razão dos R. O campo é preenchido com o τ da varredura atual.
   - Para resolver o τ, as varreduras precisam ir até 1–2,4 kHz.
3. **Guardar calibração**: nada é gravado sem este clique, então guarde só as calibrações úteis (curva limpa e repetível). O botão calcula a sensibilidade relativa `M(f) = S(f)·fⁿ`, com o n da referência (1,5 na folha em OPC, 1 nas referências da câmara), e a fase do sistema. Entram todos os pontos com SNR suficiente e não excluídos com clique, inclusive a ressonância da célula, que é justamente o que a calibração corrige. Também procura a **faixa plana** dentro de ±tol dB (padrão de ±1 dB). Salva `CAL_[<amostra>_]microfone_<célula>_*.csv` e `.png`. O cabeçalho registra os τ, a linha `OPT101_tau_sensor_s` (0 = sem correção) e as linhas `Referencia`, `Celula`, `Expoente_teorico`, `L_um`/`alpha_cm2_s` (referências de Al) e `Verificada = sim|nao`, com o resultado da verificação.
   - Toda calibração nova nasce **não verificada** (⚠ na lista e no título do PNG, aviso sempre que for usada) até passar no passo 5. A forma da própria referência vai para o arquivo só como informação (`# Verificacao: forma da referência: …`), e não há mais pergunta antes de gerar.
   - O cabeçalho também grava `# Ressonancia_f0_Hz`, o pico da célula achado acima de 250 Hz. Ao aplicar a calibração numa varredura cuja ressonância difere mais de 3 %, aparece um aviso: a amostra provavelmente tem altura diferente da referência (o volume livre muda f₀) e, perto do pico, a correção não vale.
   - Calibrações das versões anteriores (sem essas linhas) são lidas como **Folha de Al, OPC**, sem verificação registrada.
   - Se uma calibração for aplicada a uma varredura com a escolha oposta de correção, a interface avisa.
   - Calibrações **sem** essa linha recebem o aviso "Calibração antiga": foram feitas com o firmware anterior ao marcador de modulação corrigido (23/10/2026 14:43, ver [03_Firmware_STM32.md](03_Firmware_STM32.md)) ou com a correção pelo τ efetivo. Nesses casos a fase do sistema não é comparável (td ~100 µs maior). Gere uma calibração nova.
4. A calibração nova já aparece selecionada em **Calibração:**, na linha superior. Marque **Usar**: as varreduras em frequência do Modo Duplo passam a ser corrigidas por ela, e os pontos fora da faixa calibrada ficam ocultos. O CSV exportado registra no cabeçalho o nome do arquivo de calibração usado. Os dados gravados continuam brutos.
5. **Confira com outra referência.** Com a calibração aplicada (**Usar**), meça uma segunda referência de material diferente, na mesma altura e montagem (ex.: calibrou com o negro de fumo, confira com a fita preta ou o Al pintado), escolha-a em **Referência** e clique em **Verificar calibração**. A interface ajusta n e mede, dentro da Faixa, o desvio de f⁻ⁿ e a variação da fase. Passa se |n − n esperado| ≤ 0,15, desvio ≤ 1,5 dB rms e fase constante ± 10° rms. O resultado vai para o arquivo da calibração (`# Verificada = sim|nao` e `# Verificacao_2a_referencia: aprovada|reprovada - …`), e a lista é atualizada. Se a referência escolhida for a mesma da calibração, o botão só mede a repetibilidade e não marca nada. Se reprovar, as duas referências discordam: uma não é ideal nessa faixa ou a montagem mudou (altura, vedação, feixe). Refaça ou use uma terceira referência para decidir. Em 10/11/2026, a calibração com fita conferida com o Al pintado entre 159 e 682 Hz deu fase constante ± 2° e 1,3 dB rms, mas n = 0,76: reprovada pelo expoente.

**Boas práticas na câmara:** amostras e referências na mesma altura (mesmo volume livre, mesma f₀); feixe inteiro na amostra, sem raspar a borda nem a parede; furo de equalização fechado igual em todas as medidas; janela limpa (poeira e gordura absorvem e somam sinal, o que pesa com amostras refletoras); repita a referência para conhecer a repetibilidade antes de julgar a verificação.

## Arquivos gerados (`Medidas/`)

Todos os arquivos são CSV em UTF-8, com cabeçalho de comentários (`#`) que traz os parâmetros. Cada CSV tem um PNG com o mesmo nome.

| Origem | Nome do arquivo | Colunas |
|---|---|---|
| Salvar (Lock-In) | `LockIn_<f>Hz_<data>` | Tempo_s, Magnitude, Fase_Graus |
| Salvar (Valor Médio) | `ValorMedio_<f>Hz_<data>` | Tempo_s, ADC_Medio [, Fit_Exp] |
| Varredura F | `OPT101_F_varredura_f<ini>_f<fim>_<passo>_<data>` (ou `INMP441_…`) | Frequencia_Hz, Magnitude_Media, Magnitude_DesvioPadrao, Fase_Media_Graus, Fase_DesvioPadrao_Graus, DC_Offset_Medio |
| Varredura P | `OPT101_P_varredura_p<ini>_p<fim>_<passo>_f<f>Hz_<data>` (ou `INMP441_…`) | PWM_Pct, (mesmas colunas) |
| Modo Duplo, PWM | `DUPLO_casada_pwm<ini>_<fim>_f<f>Hz_<data>` | PWM_Pct, OPT101_R, OPT101_R_DP, INMP441_R, INMP441_R_DP, INMP441_Fase_Graus, INMP441_Fase_DP, OPT101_Fase_Graus, OPT101_Fase_DP |
| Modo Duplo, freq. | `DUPLO_freq_<ini>_<fim>Hz_pwm<p>_<data>` | Frequencia_Hz, (mesmas colunas) |
| Calibração | `CAL_[<amostra>_]microfone_<OPC\|Camara>_<ini>_<fim>Hz_<data>` | Frequencia_Hz, Sensibilidade_Rel, Sensibilidade_Rel_DP, Sensibilidade_Fit, Fase_Sistema_Graus, Fase_DP, Valido, Faixa_Plana, No_Ajuste |

Com o campo **Amostra** preenchido, todos os nomes começam com `<amostra>_` (ex.: `Grafite_OPT101_F_varredura_…`). A exceção é a calibração, que começa com `CAL_` e só depois traz o nome da amostra: `CAL_<amostra>_microfone_…` (sem amostra: `CAL_microfone_…`). "Usar última calibração" pega o arquivo `CAL_*microfone_*.csv` mais recente, com qualquer nome de amostra. O formato de `<data>` é `AAAAMMDD_HHMMSS`. Os dados do Modo Duplo são sempre gravados **brutos**, mesmo com a calibração aplicada no gráfico.

## Especificações resumidas

| Item | OPT101 | INMP441 |
|---|---|---|
| Taxa de amostragem | 200 kS/s crus; 200/OSR kS/s depois da sobreamostragem (padrão 12,5 kS/s) | 48 000 S/s exatos |
| Resolução | 12 bits por amostra; escala 0–16 380 (média × 4) | 24 bits com sinal |
| Banda útil | 0 – FS/2 (6,25 kHz com OSR 16) | 0 – 24 kHz |
| Referência do lock-in | PLL por software, travado nas bordas do bit REF | Numérica (sequência I2S + marcador de partida) |
| Demodulação | Quadratura, passa-baixas de 2 polos em cascata, remoção de DC com passa-altas de 1 polo | idem |
| Saída do lock-in | ≈50 pontos/s | 20 pontos/s (blocos de 2400 amostras) |
| Filtro de rede | Notches em 60 Hz e harmônicos até 1,5 kHz (opcional) | idem |
| Modulação | 0,1 – 5000 Hz (ou contínuo) | — |
| Potência | PWM de 5 kHz, 0 – 100 % em passos de 0,1 % | — |
| Atualização da tela | 25 quadros/s | — |

**Correção da média (OPT101):** cada amostra óptica é a média de OSR conversões do ADC (80 µs com OSR 16). Essa média atenua a fundamental por sin(πf·OSR/200 kHz)/(OSR·sin(πf/200 kHz)): com OSR 16, −1 % em 1 kHz, −4 % em 2 kHz e −9 % em 3 kHz; com OSR 1, nada. A magnitude do lock-in do OPT101 já sai dividida por esse fator, então os valores de R gravados estão corrigidos. A fase não precisa dessa correção: a referência (bit REF, maioria das OSR amostras) é tirada da mesma janela. O atraso fixo da referência, (OSR−1)/2 amostras de 5 µs, entra na fase digital usada pelos ajustes do Modo Duplo.

**Detalhes do PLL (OPT101):** o PLL trava quando o período entre bordas está dentro de ±(2 amostras + 0,1 %) do nominal. Os ganhos são Kp = 0,05 e Ki = Kp²/4, e a frequência fica limitada a ±5 % da nominal. O PLL destrava se o erro médio de fase passar de 1,1 rad ou se ficar sem bordas por 10 s.
