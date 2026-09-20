# Приложение W — Windows

**Коллектор v3.0 под Windows не работает** (решение владельца D13): он рассчитан
на POSIX-окружение. На рабочем ПК под Windows аудит проводится вручную по этому
приложению, и в шапке отчёта пишется «коллектор не запускался, данные сняты вручную».

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
