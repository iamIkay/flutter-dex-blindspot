| behaviour | native | native_r8 | flutter_default | flutter_obfuscated |
|---|---|---|---|---|
| B1_location | 2 caller methods, 2 app-own | 2 caller methods, 1 app-own (2 after deobf) | 4 caller methods, 0 app-own (0 after deobf) | 4 caller methods, 0 app-own (0 after deobf) |
| B2_contacts_count | 1 caller methods, 1 app-own | 1 caller methods, 1 app-own (1 after deobf) | 63 caller methods, 0 app-own (0 after deobf) | 63 caller methods, 0 app-own (0 after deobf) |
| B3_https_post | 3 caller methods, 2 app-own; strings: DEX | 2 caller methods, 2 app-own (2 after deobf); strings: DEX | 0 caller methods, 0 app-own; strings: libapp.so | 0 caller methods, 0 app-own; strings: libapp.so |
| B4_private_file | 25 caller methods, 1 app-own; strings: DEX | 3 caller methods, 1 app-own (1 after deobf); strings: DEX | 11 caller methods, 0 app-own (0 after deobf); strings: libapp.so | 11 caller methods, 0 app-own (0 after deobf); strings: libapp.so |
| B5_dummy_key | strings: DEX | strings: DEX | strings: libapp.so | strings: libapp.so |
