"""Gradio App entry point."""

import collections
import json

import gradio as gr

from env_data_mcp.server import mcp


def _inputs_from_schema(parameters: dict) -> list:
    props = parameters.get("properties", {})
    required = set(parameters.get("required", []))
    inputs = []
    for name, schema in props.items():
        label = f"{name.replace('_', ' ').title()}{'*' if name in required else ''}"
        anyof_types = {s.get("type") for s in schema.get("anyOf", [])}
        t = schema.get("type") or anyof_types
        r = schema.get("$ref")
        default = schema.get("default")
        if t:
            if "number" in t or "integer" in t:
                inputs.append(gr.Number(label=label, value=default))
            elif "array" in t:
                if isinstance(default, (list, set, frozenset)):
                    default = ", ".join(str(v) for v in default)
                inputs.append(gr.Textbox(label=f"{label} (comma-separated)", value=default or ""))
            elif "string" in t:
                inputs.append(
                    gr.Textbox(label=label, value=str(default) if default is not None else "")
                )
            else:
                msg = f"Unknown input type '{t}'"
                raise TypeError(msg)
            continue
        elif r:
            keys = r.lstrip("#/").split("/")
            data = parameters
            for key in keys:
                data = data[key]
            enum_vals = data.get("enum", [])
            inputs.append(
                gr.Dropdown(
                    label=label, choices=enum_vals, value=(default if default else enum_vals[0])
                )
            )
        else:
            msg = f"Unknown input schema '{schema}'"
            raise TypeError(msg)
    return inputs


def _make_fn(tool_fn, parmaeters):
    props = list(parmaeters.get("properties", {}).items())

    def wrapped(*args):
        kwargs = {}
        for (name, schema), val in zip(props, args, strict=True):
            anyof_typs = {s.get("type") for s in schema.get("anyOf", [])}
            t = schema.get("type") or anyof_typs
            if val == "" or val is None:
                if "default" in schema:
                    kwargs[name] = schema["default"]
            elif "array" in t:
                try:
                    kwargs[name] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    kwargs[name] = [v.strip() for v in str(val).split(",") if v.strip()]
            else:
                kwargs[name] = val
        return tool_fn(**kwargs)

    return wrapped


def launch_gui():
    tools_list = mcp._tool_manager.list_tools()
    print(f"[dashboard] {len(tools_list)} tools found")

    CATEGORIES = {
        "ESS-DIVE": "essdive",
        "GBIF": "gbif",
        "NASA POWER": "nasa_power",
        "OpenAQ": "openaq",
        "Sentinel-5 TROPOMI": "tropomi",
        "SoilGrids": "soilgrids",
        "USDA SSURGO": "ssurgo",
    }

    subcategories = {
        prefix: {
            subcat or "primary"
            for tool in tools_list
            if tool.name.lower().startswith(prefix)
            for subcat in [
                tool.name.lower()
                .removeprefix(f"{prefix}_")
                .removesuffix("available_variables")
                .removesuffix("available_rule_names")
                .removesuffix("point_query")
                .removesuffix("bbox_query")
                .strip("_")
            ]
        }
        for prefix in CATEGORIES.values()
    }

    grouped_tools = collections.defaultdict(lambda: collections.defaultdict(list))
    uncategorized_tools = []

    for tool in tools_list:
        matched = False
        for cat_label, prefix in CATEGORIES.items():
            if tool.name.lower().startswith(prefix):
                for subcat_label in subcategories[prefix]:
                    subcat_str = f"_{subcat_label}" if subcat_label != "primary" else ""
                    if tool.name.lower().startswith(f"{prefix}{subcat_str}"):
                        grouped_tools[cat_label][subcat_label].append(tool)
                        matched = True
                        break
                if not matched:
                    grouped_tools[cat_label]["additional_tools"].append(tool)
        if not matched:
            uncategorized_tools.append(tool)

    with gr.Blocks(title="Environmental Data Explorer", theme=gr.themes.Citrus()) as gui:  # type: ignore[reportPrivateImportUsage]
        gr.Markdown("# Environmental Data Explorer")
        gr.Markdown("Directly query environmental datasets.")

        with gr.Tabs(selected=0):
            for cat_label, prefix in CATEGORIES.items():
                if cat_label not in grouped_tools:
                    continue

                with gr.Tab(cat_label):
                    gr.Markdown(f"### {cat_label}")

                    for subcat_label in subcategories[prefix]:
                        with gr.Tab(subcat_label):
                            for tool in grouped_tools[cat_label][subcat_label]:
                                with gr.Accordion(
                                    tool.name.removeprefix(f"{prefix}_")
                                    .removeprefix(f"{subcat_label}")
                                    .lstrip("_")
                                    .replace("_", " ")
                                    .title(),
                                    open=False,
                                ):
                                    gr.Markdown(tool.description or "")
                                    inputs = _inputs_from_schema(tool.parameters)
                                    output = gr.JSON(label="Response")
                                    gr.Button("Submit").click(  # type: ignore[reportAttributeAccessIssue]
                                        fn=_make_fn(tool.fn, tool.parameters),
                                        inputs=inputs,
                                        outputs=output,
                                    )
            if uncategorized_tools:
                with gr.Tab("Prototyped Tools"):
                    for tool in uncategorized_tools:
                        with gr.Accordion(tool.name.replace("_", " ").title(), open=False):
                            gr.Markdown(tool.description or "")
                            inputs = _inputs_from_schema(tool.parameters)
                            output = gr.JSON(label="Response")
                            gr.Button("Submit").click(  # type: ignore[reportAttributeAccessIssue]
                                fn=_make_fn(tool.fn, tool.parameters),
                                inputs=inputs,
                                outputs=output,
                            )

        gui.launch(mcp_server=True)


def main():
    launch_gui()


if __name__ == "__main__":
    main()
