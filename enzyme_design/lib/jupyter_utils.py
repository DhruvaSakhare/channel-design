"""
Build an LSF job-array submit script.

GPU-aware (adds `#BSUB -gpu`), optionally loads a CUDA module, and always
sets a wall time -- many queues default to 15 minutes, so -W is not optional.

Queue names, the conda profile and the environment are all site-specific and
are passed in by the caller from partial_diffusion.site.
"""
import math
import os


def make_sub_script(
    cmds_file,
    n_task,
    group_size=10,
    mem="10G",
    queue="hpc",
    job_name="job",
    cores=4,
    time_limit="12:00",
    conda_sh="",
    python_path=None,
    env=None,
    gpu=True,
    gpu_spec="num=1:mode=exclusive_process",
    cuda_module="cuda/12.4",
):
    """
    Generate an LSF job-array submit script from a .cmds file (one command per line).

    Each array task runs `group_size` consecutive lines. The script is written
    next to cmds_file with a .sh extension; the path is returned.
    """
    n_arrays = math.ceil(n_task / group_size)
    out_script = cmds_file.replace(".cmds", ".sh")
    logs = os.path.join(os.path.dirname(cmds_file), "logs")

    lines = [
        "#!/bin/sh",
        f"#BSUB -q {queue}",
        f"#BSUB -J {job_name}[1-{n_arrays}]",
        f"#BSUB -n {cores}",
        '#BSUB -R "span[hosts=1]"',
        f'#BSUB -R "rusage[mem={mem}]"',
        f"#BSUB -W {time_limit}",
    ]
    if gpu:
        lines.append(f'#BSUB -gpu "{gpu_spec}"')
    lines += [
        f"#BSUB -o {logs}/%J_%I.out",
        f"#BSUB -e {logs}/%J_%I.err",
        "",
        f'mkdir -p "{logs}"',
        "",
    ]

    if cuda_module:
        lines += [f"module load {cuda_module}", ""]

    if env:
        # conda_sh is empty when the environment is already active, which is
        # the normal case outside a batch scheduler.
        if conda_sh:
            lines += [f'source "{conda_sh}"']
        lines += [f'conda activate "{env}"', ""]

    if python_path:
        lines += [f'export PYTHONPATH="{python_path}:${{PYTHONPATH:-}}"', ""]

    lines += [
        f"CMDS_FILE={cmds_file}",
        f"GROUP_SIZE={group_size}",
        "",
        "START=$(( (LSB_JOBINDEX - 1) * GROUP_SIZE ))",
        "END=$(( START + GROUP_SIZE ))",
        "",
        "i=0",
        "while IFS= read -r cmd; do",
        '    if [ "$i" -ge "$START" ] && [ "$i" -lt "$END" ]; then',
        '        echo "Running task $i: $cmd"',
        '        eval "$cmd"',
        "    fi",
        "    i=$((i+1))",
        'done < "$CMDS_FILE"',
        "",
        'echo "Done at $(date)"',
    ]

    with open(out_script, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"Submit script written: {out_script}")
    return out_script
