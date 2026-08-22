ROWS = (
 ("PROVIDER:READ","Read","low","aidn.provider.list",None),
 ("RUNTIME:READ","Read","low","aidn.runtime.instances",None),
 ("STEWARD:READ","Read","low","aidn.steward.status aidn.steward.context aidn.steward.decide aidn.steward.reasoning.providers aidn.steward.reasoning.route aidn.steward.escalations aidn.steward.escalation.get",None),
 ("STEWARD:ESCALATE","Actions","medium","aidn.steward.escalate aidn.steward.escalation.plan aidn.steward.escalation.verify aidn.steward.escalation.cancel",None),
 ("STEWARD:REASON","Actions","high","aidn.steward.reasoning.invoke","steward_reason"),
)
