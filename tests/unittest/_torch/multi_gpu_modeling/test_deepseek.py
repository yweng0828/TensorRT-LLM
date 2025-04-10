import asyncio
from difflib import SequenceMatcher
from pathlib import Path

import pytest
import torch
from utils.llm_data import llm_models_root
from utils.util import getSMVersion

from tensorrt_llm import SamplingParams
from tensorrt_llm._torch import LLM
from tensorrt_llm._torch.pyexecutor.config import PyTorchConfig
from tensorrt_llm.llmapi import KvCacheConfig, MTPDecodingConfig
from tensorrt_llm.llmapi.utils import get_total_gpu_memory

# Test combinations for different scenarios
# Each tuple contains: (tp_size, pp_size, ep_size, mtp_nextn, enable_dp, enable_cuda_graph, enable_overlap_scheduler, test_id)
TEST_COMBINATIONS = [
    # single-gpu test
    # basic test
    (1, 1, 1, 0, False, False, False,
     "tp1_pp1_ep1_nextn0_disable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (1, 1, 1, 0, True, False, False,
     "tp1_pp1_ep1_nextn0_enable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (1, 1, 1, 0, False, True, False,
     "tp1_pp1_ep1_nextn0_disable_dp_enable_cuda_graph_disable_overlap_scheduler"
     ),
    (1, 1, 1, 0, False, False, True,
     "tp1_pp1_ep1_nextn0_disable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (1, 1, 1, 0, True, True, True,
     "tp1_pp1_ep1_nextn0_enable_dp_enable_cuda_graph_enable_overlap_scheduler"),
    # mtp test
    (1, 1, 1, 2, False, False, False,
     "tp1_pp1_ep1_nextn2_disable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (1, 1, 1, 2, False, False, True,
     "tp1_pp1_ep1_nextn2_disable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (1, 1, 1, 2, False, True, True,
     "tp1_pp1_ep1_nextn2_disable_dp_enable_cuda_graph_enable_overlap_scheduler"
     ),
    (1, 1, 1, 2, True, False, True,
     "tp1_pp1_ep1_nextn2_enable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (1, 1, 1, 2, True, True, True,
     "tp1_pp1_ep1_nextn2_enable_dp_enable_cuda_graph_enable_overlap_scheduler"),
    # multi-gpu test
    # tp4
    (4, 1, 1, 0, False, False, False,
     "tp4_pp1_ep1_nextn0_disable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (4, 1, 1, 0, True, False, False,
     "tp4_pp1_ep1_nextn0_enable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (4, 1, 1, 0, False, True, False,
     "tp4_pp1_ep1_nextn0_disable_dp_enable_cuda_graph_disable_overlap_scheduler"
     ),
    (4, 1, 1, 0, False, False, True,
     "tp4_pp1_ep1_nextn0_disable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (4, 1, 1, 0, True, True, True,
     "tp4_pp1_ep1_nextn0_enable_dp_enable_cuda_graph_enable_overlap_scheduler"),
    #tp4, mtp2
    (4, 1, 1, 2, False, False, False,
     "tp4_pp1_ep1_nextn2_disable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (4, 1, 1, 2, False, False, True,
     "tp4_pp1_ep1_nextn2_disable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (4, 1, 1, 2, False, True, True,
     "tp4_pp1_ep1_nextn2_disable_dp_enable_cuda_graph_enable_overlap_scheduler"
     ),
    (4, 1, 1, 2, True, False, True,
     "tp4_pp1_ep1_nextn2_enable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (4, 1, 1, 2, True, True, True,
     "tp4_pp1_ep1_nextn2_enable_dp_enable_cuda_graph_enable_overlap_scheduler"),
    # tp4, ep4
    (4, 1, 4, 0, False, False, False,
     "tp4_pp1_ep4_nextn0_disable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (4, 1, 4, 0, True, False, False,
     "tp4_pp1_ep4_nextn0_enable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (4, 1, 4, 0, False, True, False,
     "tp4_pp1_ep4_nextn0_disable_dp_enable_cuda_graph_disable_overlap_scheduler"
     ),
    (4, 1, 4, 0, False, False, True,
     "tp4_pp1_ep4_nextn0_disable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (4, 1, 4, 0, True, True, True,
     "tp4_pp1_ep4_nextn0_enable_dp_enable_cuda_graph_enable_overlap_scheduler"),
    #tp4, ep4, mtp2
    (4, 1, 4, 2, False, False, False,
     "tp4_pp1_ep4_nextn2_disable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (4, 1, 4, 2, False, False, True,
     "tp4_pp1_ep4_nextn2_disable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (4, 1, 4, 2, False, True, True,
     "tp4_pp1_ep4_nextn2_disable_dp_enable_cuda_graph_enable_overlap_scheduler"
     ),
    (4, 1, 4, 2, True, False, True,
     "tp4_pp1_ep4_nextn2_enable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (4, 1, 4, 2, True, True, True,
     "tp4_pp1_ep4_nextn2_enable_dp_enable_cuda_graph_enable_overlap_scheduler"),
    #tp2, pp2
    (2, 2, 1, 0, False, False, False,
     "tp2_pp2_ep1_nextn0_disable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (2, 2, 1, 0, True, False, False,
     "tp2_pp2_ep1_nextn0_enable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (2, 2, 1, 0, False, True, False,
     "tp2_pp2_ep1_nextn0_disable_dp_enable_cuda_graph_disable_overlap_scheduler"
     ),
    (2, 2, 1, 0, False, False, True,
     "tp2_pp2_ep1_nextn0_disable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (2, 2, 1, 0, True, True, True,
     "tp2_pp2_ep1_nextn0_enable_dp_enable_cuda_graph_enable_overlap_scheduler"),
    #tp2, pp2, mtp2
    (2, 2, 1, 2, False, False, False,
     "tp2_pp2_ep1_nextn2_disable_dp_disable_cuda_graph_disable_overlap_scheduler"
     ),
    (2, 2, 1, 2, False, False, True,
     "tp2_pp2_ep1_nextn2_disable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (2, 2, 1, 2, False, True, True,
     "tp2_pp2_ep1_nextn2_disable_dp_enable_cuda_graph_enable_overlap_scheduler"
     ),
    (2, 2, 1, 2, True, False, True,
     "tp2_pp2_ep1_nextn2_enable_dp_disable_cuda_graph_enable_overlap_scheduler"
     ),
    (2, 2, 1, 2, True, True, True,
     "tp2_pp2_ep1_nextn2_enable_dp_enable_cuda_graph_enable_overlap_scheduler"),
]


def similar(a, b, threshold=0.9):
    "similar compare a and b "
    return SequenceMatcher(None, a, b).ratio() >= threshold


@pytest.mark.parametrize("model_name", ["DeepSeek-V3-Lite"],
                         ids=["deepseekv3_lite"])
@pytest.mark.parametrize("backend", ["TRTLLM"], ids=["trtllm"])
@pytest.mark.parametrize("quant", ["bf16", "fp8", "fp4"],
                         ids=["bf16", "fp8", "fp4"])
@pytest.mark.parametrize("test_config", TEST_COMBINATIONS, ids=lambda x: x[-1])
def test_deepseek(model_name, backend, quant, test_config):
    tp_size, pp_size, ep_size, mtp_nextn, enable_dp, enable_cuda_graph, enable_overlap_scheduler, _ = test_config

    model_path = {
        "bf16": "bf16",
        "fp8": "fp8",
        "fp4": "nvfp4_moe_only",
    }
    assert quant in model_path.keys()

    is_fp8 = quant == "fp8"
    is_fp4 = quant == "fp4"

    if (not enable_overlap_scheduler and enable_cuda_graph and not enable_dp
            and mtp_nextn == 0 and ep_size == 1 and pp_size == 4
            and tp_size == 1 and is_fp8):

        pytest.skip("https://nvbugspro.nvidia.com/bug/5189673")

    if ep_size > tp_size:
        pytest.skip(
            f"Expert parallel size {ep_size} must be less than or equal to tensor parallel size {tp_size}"
        )

    if torch.cuda.device_count() < tp_size * pp_size:
        pytest.skip(f"Not enough GPUs available, need {tp_size * pp_size} "
                    f"but only have {torch.cuda.device_count()}")

    if is_fp8 and getSMVersion() != 90:
        pytest.skip(f"FP8 is not supported in this SM version {getSMVersion()}")

    if is_fp4 and getSMVersion() < 100:
        pytest.skip(f"FP4 is not supported in this SM version {getSMVersion()}")

    if is_fp4 and mtp_nextn > 0:
        pytest.skip(f"FP4 checkpoint has no MTP weights")

    if mtp_nextn > 0 and getSMVersion() < 90:
        pytest.skip(f"Only Hopper and Blackwell MLA kernel can support MTP now")

    if pp_size > 1 and mtp_nextn > 0:
        pytest.skip(
            "PP + MTP is not supported: https://nvbugspro.nvidia.com/bug/5170160"
        )
    if pp_size > 2 and enable_cuda_graph and enable_overlap_scheduler:
        pytest.skip(
            "Race condition causes incorrect output for some requests: https://nvbugspro.nvidia.com/bug/5177565"
        )

    if get_total_gpu_memory(0) < 60 * 1024**3:
        pytest.skip(f"Not enough GPU memory to run. {get_total_gpu_memory(0)}")

    prompts = [
        "The president of the United States is",
    ] * 32

    expected_outputs = [
        " the head of state and head of government of the",
    ] * 32

    pytorch_config = PyTorchConfig(
        enable_overlap_scheduler=enable_overlap_scheduler,
        use_cuda_graph=enable_cuda_graph,
        kv_cache_dtype="auto",
        attn_backend=backend,
    )

    mtp_config = MTPDecodingConfig(
        num_nextn_predict_layers=mtp_nextn) if mtp_nextn > 0 else None

    model_dir = str(llm_models_root() / model_name / model_path[quant])

    assert Path(model_dir).exists()

    llm = LLM(model=model_dir,
              tensor_parallel_size=tp_size,
              pipeline_parallel_size=pp_size,
              enable_chunked_prefill=False,
              pytorch_backend_config=pytorch_config,
              moe_expert_parallel_size=ep_size,
              moe_tensor_parallel_size=-1,
              enable_attention_dp=enable_dp,
              kv_cache_config=KvCacheConfig(enable_block_reuse=False),
              speculative_config=mtp_config)

    with llm:
        outputs = llm.generate(
            prompts,
            sampling_params=SamplingParams(max_tokens=10),
        )

    assert len(outputs) == len(expected_outputs), "Output length mismatch"
    for output, expected in zip(outputs, expected_outputs):
        output_text = output.outputs[0].text
        # print(output_text)
        # print(output.outputs[0].token_ids)
        # Limited by the kv cache length, the output length of MTP maybe
        # a little smaller than original model.
        expected = expected[0:len(output_text)] if mtp_nextn > 0 else expected
        assert similar(output_text, expected,
                       1.0), f"Expected '{expected}' but get '{output_text}'"


@pytest.mark.parametrize("model_name", ["DeepSeek-V3-Lite"],
                         ids=["deepseekv3_lite"])
@pytest.mark.parametrize("backend", ["TRTLLM"], ids=["trtllm"])
@pytest.mark.parametrize("quant", ["bf16"])
@pytest.mark.parametrize("tp_size", [1], ids=["tp1"])
def test_deepseek_streaming(model_name, backend, quant, tp_size):
    model_path = {
        "bf16": "bf16",
        "fp8": "fp8",
        "fp4": "nvfp4_moe_only",
    }
    assert quant in model_path.keys()

    is_fp8 = quant == "fp8"
    is_fp4 = quant == "fp4"

    if torch.cuda.device_count() < tp_size:
        pytest.skip(f"Not enough GPUs available, need {tp_size} "
                    f"but only have {torch.cuda.device_count()}")

    if is_fp8 and getSMVersion() != 90:
        pytest.skip(f"FP8 is not supported in this SM version {getSMVersion()}")

    if is_fp4 and getSMVersion() < 100:
        pytest.skip(f"FP4 is not supported in this SM version {getSMVersion()}")

    if get_total_gpu_memory(0) < 60 * 1024**3:
        pytest.skip(f"Not enough GPU memory to run. {get_total_gpu_memory(0)}")

    prompts = [
        "The president of the United States is",
    ] * 32

    expected_outputs = [
        " the head of state and head of government of the",
    ] * 32

    pytorch_config = PyTorchConfig(
        enable_overlap_scheduler=False,
        use_cuda_graph=False,
        kv_cache_dtype="auto",
        attn_backend=backend,
    )

    model_dir = str(llm_models_root() / model_name / model_path[quant])

    assert Path(model_dir).exists()

    llm = LLM(model=model_dir,
              tensor_parallel_size=tp_size,
              enable_chunked_prefill=False,
              pytorch_backend_config=pytorch_config,
              moe_expert_parallel_size=-1,
              moe_tensor_parallel_size=-1,
              enable_attention_dp=False,
              kv_cache_config=KvCacheConfig(enable_block_reuse=False))

    sampling_params = SamplingParams(max_tokens=10)

    async def task(prompt: str):
        future = llm.generate_async(prompt,
                                    streaming=True,
                                    sampling_params=sampling_params)
        output = await future.aresult()
        return output.outputs[0].text

    async def test():
        tasks = [task(prompt) for prompt in prompts]
        results = await asyncio.gather(*tasks)

        assert len(results) == len(expected_outputs), "Output length mismatch"
        for result, expected in zip(results, expected_outputs):
            assert similar(result, expected,
                           1.0), f"Expected '{expected}' but get '{result}'"

    asyncio.run(test())
