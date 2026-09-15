// Literal registry bindings; a registration is not qualification.
export const registeredFlashVariants: Record<string, {spec_sha256: string; image_id: string; qualification_profile: string; max_model_len: number; mtp_speculative_tokens: number; kv_cache_memory_bytes: number}> = {
  "mia-925d7be6-c0-s1": {
    "spec_sha256": "dde4fe1f72cf91de92089a95748cee1f6a8204e351d517aa0ae46d8d27122857",
    "image_id": "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72",
    "qualification_profile": "C0-MIA-S1",
    "max_model_len": 32768,
    "mtp_speculative_tokens": 0,
    "kv_cache_memory_bytes": 2147483648
  },
  "mia-925d7be6-mtp1-fullvocab-v1": {
    "spec_sha256": "d5346e7926a72f21e888c10f224477779c17858751f956e216891914069ac00d",
    "image_id": "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72",
    "qualification_profile": "MIA-MTP1-FULLVOCAB-32K",
    "max_model_len": 32768,
    "mtp_speculative_tokens": 1,
    "kv_cache_memory_bytes": 2147483648
  },
  "mia-925d7be6-mtp2-fullvocab-v1": {
    "spec_sha256": "21aa2feb6c46ebaa0ce5a211f612df6a77667554e5c71d706bd52c610d07fc88",
    "image_id": "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72",
    "qualification_profile": "MIA-MTP2-FULLVOCAB-32K",
    "max_model_len": 32768,
    "mtp_speculative_tokens": 2,
    "kv_cache_memory_bytes": 2147483648
  },
  "mia-925d7be6-mtp3-fullvocab-v1": {
    "spec_sha256": "32268b7d267e188643ccd918054e26f8505072a704e5b574a441fd8b9b465e65",
    "image_id": "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72",
    "qualification_profile": "MIA-MTP3-FULLVOCAB-32K",
    "max_model_len": 32768,
    "mtp_speculative_tokens": 3,
    "kv_cache_memory_bytes": 2147483648
  },
  "mia-925d7be6-ctx69632-bf16kv3g-v1": {
    "spec_sha256": "d9f8e3ebaa77ac99b9d58fc029c975d9ceb3ae1fd90a6065d5af863a166e454d",
    "image_id": "sha256:da68dd27a8ef1dadd0f380178a51f0a0671dc4235933ea1ae89fdaf66295ec72",
    "qualification_profile": "MIA-NATIVE69632-BF16KV3G-MTP0",
    "max_model_len": 69632,
    "mtp_speculative_tokens": 0,
    "kv_cache_memory_bytes": 3221225472
  },
  "mia-925d7be6-mtp3-reduced47k-v2opt-v1": {
    "spec_sha256": "e71d3134f407cad3c288c21f9485c27352676dbb7de647c5b567777256702a50",
    "image_id": "sha256:29eab5a29b765eef8b6405bbe0f2d385fc1e7b5e3c7ae18ae70382a68a0a2201",
    "qualification_profile": "MIA-MTP3-REDUCED47K-V2-FULL4-MODE0-32K",
    "max_model_len": 32768,
    "mtp_speculative_tokens": 3,
    "kv_cache_memory_bytes": 2147483648
  }
};
