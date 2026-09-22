# Приложение W — Windows

**Коллектор под Windows не собирает факты** (решение владельца D13): он рассчитан
на POSIX-окружение. Полный запуск `collect.py` сразу выходит с **кодом 5** и сообщением
«идти по приложению W». Если работа идёт в WSL — запускай там: это Linux, работает весь тракт.
На «голом» Windows аудит проводится вручную, и в шапке отчёта пишется «коллектор не
запускался, данные сняты вручную».

**Что остаётся от девяти шагов:**

| Шаг | На Windows |
|---|---|
| 1. Факты | вручную, по таблицам ниже |
| 4–5. План и клинап | `cleanup.py plan` требует `facts.json` — **неприменимо**. Пункты белого списка — только руками после согласия №2 |
| 6. Песочница | `reality_check.py` требует `facts.json` — **неприменимо**, вердикт `not_checked` честный |
| 7. Самопроверка | **`collect.py --scan-file` работает** и обязательна перед показом отчёта |

Пути к настройкам агента те же (`%USERPROFILE%\.claude\`), системные отличаются.
**Честное предупреждение:** переписывать придётся почти каждую проверку, и часть из них
на Windows не имеет смысла вовсе. Не переводи их дословно.

| Проверка | PowerShell |
|---|---|
| Кто и где | `whoami; hostname; Get-ComputerInfo \| Select OsName,OsVersion` |
| Диск | `Get-PSDrive C \| Select Used,Free` |
| Крупные каталоги | `Get-ChildItem $HOME -Directory \| ForEach-Object { [PSCustomObject]@{ Имя=$_.Name; ГБ=[math]::Round((Get-ChildItem $_.FullName -Recurse -File -EA SilentlyContinue \| Measure-Object Length -Sum).Sum/1GB,2) } } \| Sort ГБ -Desc \| Select -First 10` |
| Крупные файлы | `Get-ChildItem $HOME -Recurse -File -EA SilentlyContinue \| Where Length -gt 200MB \| Sort Length -Desc \| Select -First 10 FullName,Length` |
| Процессы агентов | `Get-Process \| Where { $_.ProcessName -match 'claude\|codex\|node' } \| Select Id,ProcessName,WS` |
| Память | `Get-CimInstance Win32_OperatingSystem \| Select TotalVisibleMemorySize,FreePhysicalMemory` |
| Ключ SSH-хоста | `ssh-keygen -lf C:\ProgramData\ssh\ssh_host_ed25519_key.pub` |
| Счётчик секрета в файле | `(Select-String -Path .\CLAUDE.md -Pattern 'token\|api[_-]?key' -AllMatches).Matches.Count` |

## Чего в таблице нет, а в основном тракте есть

| Шаг | Что делать на Windows |
|---|---|
| Лимиты cgroup | **Отпадает: их нет.** Ближайший аналог — Job Objects и настройки WSL (`.wslconfig`), но у обычного рабочего ПК их нет. Пиши «неприменимо», а не «в порядке» |
| Удалённые, но открытые файлы | Штатного эквивалента нет: `openfiles /query` (нужен включённый режим) или `handle64.exe` из Sysinternals. Не стоит — это слепая зона, назови её |
| Расписания | `Get-ScheduledTask \| Where State -ne 'Disabled' \| Select TaskName,TaskPath`; заодно `Get-ScheduledTaskInfo` на «последний запуск с ошибкой» |
| Обход дома в поисках секретов | Обязательно исключить облачные каталоги (`OneDrive`, `Dropbox`, `Google Drive` и подобные): они огромны и подтягивают файлы из сети по обращению. Число всегда помечается как нижняя граница |
| Права `600` на файлах секретов | **POSIX-права на Windows недостоверны:** обычный вывод покажет `777` там, где реальные ACL закрыты. Смотреть `icacls <файл>` или `Get-Acl <файл> \| Format-List` и проверять наследование |
| Любая запись в файл фактов | `-Encoding UTF8` явно, иначе PowerShell пишет UTF-16 и доказательная база превращается в мусор |

**Отдельная находка, которой на Linux не бывает:** каталог с секретами, унаследовавший
права от облачной папки или от общей группы — так у песочницы одного из агентов оказался
доступ на чтение к каталогу с токенами. Проверяется наследованием
(`(Get-Acl <каталог>).Access | Where IsInherited -eq $true`). Наследованные разрешения
на каталоге секретов — **critical**.

**Ловушки плана правок под Windows:** `.bat` с кириллицей ломает `cmd.exe` — логику
выносят в `.ps1`; `.ps1` с кириллицей обязан быть в UTF-8 **с BOM**, иначе PowerShell 5.1
читает его как cp866 и падает на разборе.

## Что нашёл первый прогон v3 на Windows (21.09.2026)

**Песочница Codex в режиме elevated читает профиль.** Группа `CodexSandboxUsers` получает
`(OI)(CI)(RX)` на **каждую папку верхнего уровня профиля**, и Codex заново выдаёт эти
права при каждом запуске, в том числе на только что созданные папки. Отключённое
наследование спасает только вложенные каталоги (`infra\secrets` внутри проекта закрыт,
а `~\.secrets` на верхнем уровне — нет). Проверка:
`icacls $HOME\.claude, $HOME\.secrets | Select-String CodexSandboxUsers`. Если группа читает
токены входа, `.secrets`, OAuth-каталоги или историю PowerShell, это **critical**. Рецепт
для человека (вне белого списка): явный запрет, который сильнее разрешения, —
`icacls <каталог> /deny "CodexSandboxUsers:(OI)(CI)(RX)"` на `~\.claude`, `~\.secrets`,
OAuth-каталоги и `%APPDATA%\Microsoft\Windows\PowerShell\PSReadLine`.

**Облачное зеркало корня проектов — класс находки, а не исключение.** «Исключить облачные
каталоги» верно, пока облако лежит отдельной папкой. Но Drive for desktop в режиме
«Мой компьютер» зеркалирует сам корень проектов — и вместе с ним каталоги секретов и `.git`.
Признаки: временные `.tmp.drivedownload` / `.tmp.driveupload` в корне; база
`%LOCALAPPDATA%\Google\DriveFS\<id>\mirror_sqlite.db` (`root_config` — что зеркалится,
`mirror_item` — файлы). В `mirror_item` значение `local_type = 1` означает файл, а выгружен ли
он — смотри по `cloud_size` или `stable_id`, **не по `cloud_md5`**: по md5 выходит «0 выгружено»,
а на деле выгружено 73 из 73.

**История PowerShell** (`...\PSReadLine\ConsoleHost_history.txt`) хранит ключи, вставленные
в команды, — на том же прогоне там нашлись ключи Anthropic. Сканировать её, как историю shell.

**Инструмент Bash может не работать.** В сессии VS Code он получил смешанный `PATH`
(Windows-строка через `;` и пути плагинов через `:`), и не находился даже `ls`. Это
сбой сессии, а не системы: переходи на PowerShell и не записывай это в находки.

**`op vault list` может зависнуть**, ожидая разблокировки 1Password и окна биометрии.
Запускай с таймаутом, не больше 15 секунд.

**Обход дома не помещается в общий бюджет.** Иди сначала по приоритетным каталогам
(`.claude`, `.codex`, `.secrets`, `AppData\Roaming`, `Desktop`, `Downloads`, `Tools`), потом
по остальным. Алфавитный порядок при обрыве прячет именно их.
