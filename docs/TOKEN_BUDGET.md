# Token sizing

Offline measurements on 4 November 2026 using `cl100k_base`. No model calls, live Pinecone reads or re-ingestion.

| Measured local material | Median | P95 | Maximum |
|---|---:|---:|---:|
| 100 golden questions | 30 | 47 | 52 |
| 118 catalogue metadata envelopes, full internal format | 274 | 325 | 618 |
| Same catalogue, compact identifying metadata | 82 | 104 | 127 |
| 155 answered historical evaluation outputs | 184 | 447 | 629 |

Metadata envelopes use catalogue fields plus representative ingestion fields. They are not a sample of the current live vectors. Historical answers come from an earlier pipeline and are sizing references, not current quality results.

| Component | Allowance |
|---|---:|
| Current question / resolved question, each | 1,024 |
| Recent history | 2,000 |
| Formatted evidence, including identifying metadata | 8,000 |
| Complete input, including safety buffer | 14,000 |
| Safety buffer included in complete input | 512 |
| Maximum output per call | 1,500 |
| Combined request input/output accounting | 48,000 |

Current fixed instructions and duplicated structured-output schemas measured approximately 625–1,347 tokens depending on the step. These are measured overhead, not a separate truncation allowance.

A local sizing fixture retained all ten 650-token passages with long catalogue metadata: 7,419 formatted evidence tokens. With two 1,024-token questions and roughly 2,000 tokens of history, the answer prompt used 12,875 tokens including the 512-token buffer. Grading used 10,129. Output reserves another 1,500; the configured maximum input-plus-output allowance is 15,500.

The 48,000 request allowance permits ordinary KB/web flows while retaining capacity for the final answer. It is not a guarantee that every possible retry fits. Actual model traffic has not been measured here. Monitor request usage and tune after representative live runs. Tokenizer/provider differences mean this is not an exact billing or model-context guarantee.
