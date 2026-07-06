import json
import os
import xml.etree.ElementTree as ET


def build_dictionary():
    xml_path = "libs/edi_grammar/src/edi_grammar/x12/5011/X12.Segment"
    output_path = "frontend/web/public/edidescription/x12_5011.json"

    if not os.path.exists(xml_path):
        print(f"Error: Could not find {xml_path}")
        return

    tree = ET.parse(xml_path)
    root = tree.getroot()

    elements_dict = {}
    segments_dict = {}

    # Parse Elements
    elements_node = root.find("Elements")
    if elements_node is not None:
        for data_node in elements_node.findall("Data"):
            name = data_node.get("name")
            info = data_node.get("info")
            if name and info:
                elements_dict[name] = info

    # Parse Segments using iter to find all Segment elements regardless of depth
    for segment_node in tree.iter("Segment"):
        name = segment_node.get("name")
        info = segment_node.get("info")

        elements_list = []
        for data_node in segment_node.findall("Data"):
            ref = data_node.get("ref")
            if ref:
                elements_list.append(ref)

        if name and info:
            segments_dict[name] = {"info": info, "elements": elements_list}

    output = {"segments": segments_dict, "elements": elements_dict}

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(
        f"Successfully wrote {output_path} with {len(segments_dict)} segments and {len(elements_dict)} elements."
    )


if __name__ == "__main__":
    build_dictionary()
