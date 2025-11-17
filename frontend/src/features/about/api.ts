import { api } from "../../lib/api";
import { AboutInfo } from "./types";

export async function fetchAboutInfo(): Promise<AboutInfo> {
  const response = await api.get<AboutInfo>("/about");
  return response.data;
}
