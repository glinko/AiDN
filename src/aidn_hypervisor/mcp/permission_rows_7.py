ROWS = (
 ("PROVIDER:WRITE","Actions","high","aidn.provider.attach","provider_attach"),
 ("BUNDLE:ACTIVATE","Actions","high","aidn.bundle.activate","bundle_activate"),
 ("BUNDLE:RETIRE","Actions","critical","aidn.bundle.retire","bundle_retire"),
 ("RUNTIME:WRITE","Actions","critical","aidn.runtime.drain aidn.runtime.stop aidn.runtime.pin aidn.runtime.unpin","runtime_control"),
)
