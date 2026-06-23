export const getColor = (index, total) => {
  const hue = ((index * 360) / Math.max(total, 1)) % 360;
  return `hsl(${hue}, 70%, 50%)`;
};

export const createColorMap = (names) => {
  const colorMap = {};
  names.forEach((name, index) => {
    colorMap[name] = getColor(index, names.length);
  });
  return colorMap;
};
