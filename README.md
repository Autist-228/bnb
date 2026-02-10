# BNB Sniper Bot - PancakeSwap V2 + ML

Снайпер бот для новых токенов на PancakeSwap V2 (BSC) с машинным обучением.

## Возможности

- **Мониторинг новых пар** — отслеживание PairCreated событий на PancakeSwap Factory в реальном времени
- **Фильтр ликвидности** — покупка только токенов с ликвидностью >= 1500 BNB (настраивается)
- **Honeypot детекция** — симуляция buy/sell для определения, можно ли продать токен
- **Rug Pull защита** — проверка ownership, mint функций, концентрации холдеров
- **ML модель** — GradientBoosting классификатор оценивает токен по 12 параметрам
- **Авто Buy/Sell** — мгновенная покупка при прохождении всех проверок
- **Take Profit / Stop Loss** — автоматическая продажа при достижении цели
- **Быстрый polling** — обновление каждые 100ms (настраивается)

## Архитектура

```
main.py              - Точка входа, CLI
train_model.py       - Обучение ML модели
src/
  config.py          - Конфигурация, ABI контрактов
  blockchain.py      - Подключение к BSC
  monitor.py         - Мониторинг новых пар
  liquidity.py       - Проверка ликвидности
  safety.py          - Анализ безопасности (honeypot, rug pull)
  ml_model.py        - ML модель скоринга токенов
  sniper.py          - Исполнение buy/sell
  bot.py             - Оркестратор бота
  utils.py           - Утилиты, логирование
```

## ML Модель

GradientBoosting классификатор анализирует 12 фичей:

| Фича | Описание |
|------|----------|
| is_not_honeypot | Можно ли продать токен |
| buy_tax | Налог на покупку % |
| sell_tax | Налог на продажу % |
| ownership_renounced | Владелец отказался от контракта |
| no_proxy | Нет прокси-контракта |
| holder_count | Количество холдеров |
| top_holder_pct | % токенов у топ-холдера |
| not_mintable | Нет функции mint |
| liquidity_locked | Ликвидность залочена |
| liquidity_bnb | Ликвидность в BNB |
| token_age_seconds | Возраст токена |
| price_impact_pct | Price impact при покупке |

## Установка

```bash
# Клонировать репо
git clone https://github.com/Autist-228/bnb.git
cd bnb

# Установить зависимости
pip install -r requirements.txt

# Скопировать конфиг
cp .env.example .env

# Заполнить .env своими данными
nano .env
```

## Настройка .env

```env
# BSC нода (можно использовать свою для максимальной скорости)
BSC_HTTPS_URL=https://bsc-dataseed1.binance.org

# Кошелёк
PRIVATE_KEY=ваш_приватный_ключ
WALLET_ADDRESS=ваш_адрес_кошелька

# Параметры бота
BUY_AMOUNT_BNB=0.1          # Сумма покупки в BNB
MIN_LIQUIDITY_BNB=1500      # Минимальная ликвидность
MAX_BUY_TAX=10               # Макс. налог на покупку %
MAX_SELL_TAX=10               # Макс. налог на продажу %
SLIPPAGE_PERCENT=12           # Допустимый slippage %
GAS_PRICE_GWEI=5              # Цена газа
GAS_LIMIT=500000              # Лимит газа
TAKE_PROFIT_PERCENT=100       # Тейк профит %
STOP_LOSS_PERCENT=30          # Стоп лосс %
ML_MIN_SCORE=0.7              # Мин. ML скор для покупки
POLL_INTERVAL_MS=100          # Интервал опроса в мс
```

## Запуск

```bash
# Базовый запуск
python main.py

# С параметрами через CLI
python main.py --buy-amount 0.05 --min-liquidity 2000 --ml-score 0.8

# С высоким профитом
python main.py --take-profit 200 --stop-loss 15

# Максимальная скорость
python main.py --poll-interval 50 --gas-price 7

# Дебаг режим
python main.py --debug
```

## Обучение ML модели

```bash
# Обучение на синтетических данных (по умолчанию)
python train_model.py

# Обучение на реальных данных
python train_model.py --data trades.csv
```

### Формат CSV для обучения

```csv
is_not_honeypot,buy_tax,sell_tax,ownership_renounced,no_proxy,holder_count,top_holder_pct,not_mintable,liquidity_locked,liquidity_bnb,token_age_seconds,price_impact_pct,profitable
1,3.0,3.0,1,1,150,15.0,1,1,5000,120,0.5,1
0,45.0,90.0,0,0,5,85.0,0,0,200,10,25.0,0
```

## Пайплайн обработки токена

```
Новая пара -> Ликвидность >= 1500 BNB? -> Honeypot проверка -> Tax проверка
     -> ML скоринг >= 0.7? -> ПОКУПКА -> Мониторинг позиции -> Take Profit / Stop Loss
```

## Рекомендации

- Используйте приватную BSC ноду для максимальной скорости
- Начинайте с маленьких сумм для тестирования
- Следите за газом и slippage
- ML модель улучшается при обучении на реальных данных ваших трейдов
- Не храните приватный ключ в открытом виде — используйте .env файл
