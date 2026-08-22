ROWS = (
 ("AUDIT:READ","Read","low","aidn.audit.query aidn.event.query aidn.event.inbox aidn.event.ack",None),
 ("HOOK:READ","Read","low","aidn.hook.list aidn.hook.get aidn.hook.deliveries aidn.hook.dead_letters aidn.hook.metrics",None),
 ("HOOK:MANAGE","Actions","high","aidn.hook.create aidn.hook.update aidn.hook.pause aidn.hook.resume aidn.hook.delete aidn.hook.test aidn.hook.ack aidn.hook.replay aidn.hook.dead_letter_retry","hook_manage"),
)
