import random
from pathlib import Path

from loguru import logger

from speech_resynthesis.data.basic import (
    get_file_under_current_path,
    get_files_under_speaker_id,
    load_concat_embs,
    load_mel,
    load_w2v,
    load_wav,
)

HOP_SIZE = 320
SEGMENT_SIZE = 32000


def load_1on1_datapath(wav_path, mel_path, w2v_path):
    """
    for normal method:
        use same single utterance as input and target
    """
    logger.info(f"loading {wav_path} data...")
    wav_list = get_file_under_current_path(wav_path, "wav")
    detail_len = len(Path(wav_path).parts) - len(Path(wav_list[0]).parts)
    result = []
    for i in wav_list:
        detail = i.parts[detail_len:]
        w2v = Path(*list(Path(w2v_path).parts + detail)).with_suffix(".pt")
        mel = Path(*list(Path(mel_path).parts + detail)).with_suffix(".npy")
        result.append((i, w2v, mel))
    return result


def load_1on2_datapath(wav_path, mel_path, w2v_path):
    """
    for self-augmentation method:
        input: pitch, formant, freq. shifting on original libritts audio and generated by w2v2
        target: original libritts audio's mel
    """
    logger.info(f"loading {wav_path} data...")
    wav_list = get_file_under_current_path(wav_path, "wav")
    detail_len = len(Path(wav_path).parts) - len(Path(wav_list[0]).parts)
    result = []
    for i in wav_list:
        detail = i.parts[detail_len:]
        mel = Path(*list(Path(mel_path).parts + detail)).with_suffix(".npy")
        w2v = Path(*list(Path(w2v_path).parts + detail)).with_suffix(".pt")
        for j in range(2):
            w2v_p = Path(str(w2v).replace(".pt", f"_perturb_{j}.pt"))
            result.append((i, w2v_p, mel))
    return result


def _load_1on1_data(wav_path, w2v_path, mel_path):
    """
    input:
        src: file in w2v_path
        ref: file in mel_path
    output:
        content_emb base on src
        target_emb base on ref (single file)
        tgt_mel(target_emb) base on ref
    """
    src_feature = load_w2v(w2v_path)
    ref_feature = load_mel(mel_path)

    content_emb = src_feature.squeeze().cpu()
    target_emb = ref_feature.squeeze().cpu()
    # print(f"w2v_path: {w2v_path}, mel_path: {mel_path}")

    src_audio, tgt_audio = get_audio_for_wandb(w2v_path, mel_path)
    return (content_emb, target_emb, target_emb, src_audio, tgt_audio)


def _load_1onmany_data(wav_path, w2v_path, mel_path, concat, include):
    """
    input:
        src: file in w2v_path
        ref: file in mel_path
    output:
        content_emb base on src
        target_emb base on ref (multiple file)
        tgt_mel base on ref which is the same content with src
    """
    src_feature = load_w2v(w2v_path)
    tgt_mel = load_mel(mel_path)
    content_emb = src_feature.squeeze().cpu()
    tgt_mel = tgt_mel.squeeze().cpu()

    mel_list = get_files_under_speaker_id(mel_path, "npy")
    random.shuffle(mel_list)

    if include:
        concat_target_emb = load_concat_embs(mel_list[: concat - 1], tgt_mel)
    else:
        mel_list.remove(mel_path)
        concat_target_emb = load_concat_embs(mel_list[:concat])

    src_audio, tgt_audio = get_audio_for_wandb(w2v_path, mel_path)
    concat_target_emb = concat_target_emb[:1000]

    return (content_emb, concat_target_emb, tgt_mel, src_audio, tgt_audio)


def get_audio_for_wandb(src_w2v_path, tgt_mel_path):
    """
    pair dataset:
    1. libritts:
        w2v: 17th_hidden/wav2vec2 #s2vc source
        mel_path: ada_input_num_mel_256/mels #s2vc target
        audio: resampled #hifigan real audio
    2. self-augmentation：
        w2v: perturb_vec #s2vc source
        mel_path: ada_input_num_mel_256/mels #s2vc target
        audio: resampled #hifigan real audio
    """
    src_w2v_path = str(src_w2v_path.with_suffix(".wav"))
    tgt_mel_path = str(tgt_mel_path.with_suffix(".wav"))

    if "/17th_hidden/wav2vec2/" in src_w2v_path:
        src_path = src_w2v_path.replace("/17th_hidden/wav2vec2/", "/resampled/")
    elif "/perturb_vec/" in src_w2v_path:
        src_path = src_w2v_path.replace("/perturb_vec/", "/perturb/")

    if "/ada_input_num_mel_256/mels/" in tgt_mel_path:
        tgt_path = tgt_mel_path.replace("/ada_input_num_mel_256/mels/", "/resampled/")

    if "src_path" not in vars() or "tgt_path" not in vars():
        raise ValueError(
            "src path doesn't match the set of audio files, plz add into this function"
        )
    # print(f"w2v_path: {src_path}, mel_path: {tgt_path}")
    return load_wav(src_path), load_wav(tgt_path)
