# n8n Workflow Manager

Управление n8n workflows: поиск, чтение, создание, правка, активация и выполнение; для записи в Bitrix — песочница, маршрут проекта или явное подтверждение.

## Когда использовать

См. полный `description` в [SKILL.md](SKILL.md) — там перечислены триггер-фразы и контекст активации.

## Что делает

См. [SKILL.md](SKILL.md) — алгоритм, формат вывода, правила.

## References

- [bitrix-api.md](references/bitrix-api.md)
- [node-templates.md](references/node-templates.md)

## Приоритет навыка

Если у проекта или пользователя есть собственный `/n8n-workflow-manager`, он имеет приоритет.
Этот вариант используется при явном вызове `/team-skills:n8n-workflow-manager` или отсутствии собственного навыка.
