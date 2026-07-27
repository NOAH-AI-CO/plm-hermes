from paddleocr import PaddleOCR, PaddleOCRVL
# ocr = PaddleOCR(
#     use_doc_orientation_classify=False,
#     use_doc_unwarping=False,
#     use_textline_orientation=False)

# # Run OCR inference on a sample image 
# result = ocr.predict(
#     input="/Users/andy/repos/NoahAgent/img.png")

# # Visualize the results and save the JSON results
# for res in result:
#     res.print()
#     res.save_to_img("output")
#     res.save_to_json("output")

# pipeline = PaddleOCRVL()
# output = pipeline.predict("/Users/andy/repos/NoahAgent/img.png")
# for res in output:
#     res.print()
#     res.save_to_json(save_path="output")
#     res.save_to_markdown(save_path="output")

def box_area(coord):
    x1, y1, x2, y2 = coord
    return max(0, x2 - x1) * max(0, y2 - y1)


def intersection_area(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    return max(0, ix2 - ix1) * max(0, iy2 - iy1)


def filter_large_boxes_overlapping_small(boxes, large_overlap_threshold=0.8, large_count_threshold=1, small_overlap_threshold=0.9):
    """
    Two-pass filtering:

    Pass 1 – Remove large boxes that overlap more than `large_overlap_threshold`
    (as a fraction of each small box's area) with MORE THAN `large_count_threshold`
    small boxes.  A box is "large" relative to another if its area is strictly greater.

    Pass 2 – Among the remaining boxes, remove any box that is mostly contained
    inside a larger box: if intersection / box_area > `small_overlap_threshold`
    and the other box is strictly larger, the smaller box is removed.
    """
    areas = [box_area(b["coordinate"]) for b in boxes]
    to_remove = set()

    # Pass 1: large boxes that swallow more than large_count_threshold small boxes
    for i in range(len(boxes)):
        if areas[i] == 0:
            continue
        overlap_count = 0
        for j in range(len(boxes)):
            if i == j or areas[i] <= areas[j]:
                continue
            small_area = areas[j]
            if small_area == 0:
                continue
            overlap = intersection_area(boxes[i]["coordinate"], boxes[j]["coordinate"]) / small_area
            if overlap > large_overlap_threshold:
                overlap_count += 1
        if overlap_count > large_count_threshold:
            to_remove.add(i)

    # Pass 2: small boxes that are ≥ small_overlap_threshold covered by a larger remaining box
    remaining = [idx for idx in range(len(boxes)) if idx not in to_remove]
    pass2_remove = set()
    for i in remaining:
        small_area = areas[i]
        if small_area == 0:
            continue
        for j in remaining:
            if i == j or j in pass2_remove or areas[j] <= areas[i]:
                continue  # j must be strictly larger than i
            overlap = intersection_area(boxes[i]["coordinate"], boxes[j]["coordinate"]) / small_area
            if overlap > small_overlap_threshold:
                pass2_remove.add(i)
                break

    to_remove |= pass2_remove
    return [b for idx, b in enumerate(boxes) if idx not in to_remove]


from paddleocr import LayoutDetection

model = LayoutDetection(model_name="PP-DocLayout-L")
# model = LayoutDetection(model_name="RT-DETR-L_wireless_table_cell_det")
# model = LayoutDetection(model_name="PP-DocBlockLayout")
output = model.predict('/Users/andy/Downloads/NCCN-AML-2024 V3_13-22_03.png', batch_size=1, layout_nms=True, threshold={2:0.08}, layout_merge_bboxes_mode="small")
for res in output:
    res.print()
    filtered = filter_large_boxes_overlapping_small(res["boxes"], large_overlap_threshold=0.8, large_count_threshold=1, small_overlap_threshold=0.9)
    res["boxes"] = filtered
    res.save_to_img(save_path="./output/")
    res.save_to_json(save_path="./output/res.json")