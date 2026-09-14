# Deterministic description: every element type is spelled out explicitly.
process: Согласование счёта на оплату
id: InvoiceApproval
lane: Бухгалтер
lane: Руководитель
lane: Казначейство

start: Счёт поступил от поставщика (message)
task[Бухгалтер]: Проверить реквизиты счёта @check
rule[Бухгалтер]: Проверить счёт по бизнес-правилам
xor: Счёт корректен?
  case Да (condition=invoice.valid == true):
    xor: Сумма превышает лимит?
      case Да (condition=invoice.amount > 100000):
        task[Руководитель]: Согласовать счёт
      else Нет:
        service: Согласовать автоматически
    and:
      branch:
        service[Казначейство]: Зарезервировать средства
      branch:
        send[Бухгалтер]: Уведомить поставщика о согласовании
    task[Казначейство]: Оплатить счёт
    end: Счёт оплачен
  else Нет:
    send[Бухгалтер]: Запросить корректный счёт
    timer: Ожидание исправленного счёта (timer=P3D)
    goto: @check
